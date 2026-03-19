import os
import asyncio
import logging
import time

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a thorough research agent. Your job is to research a given topic
and produce a comprehensive, well-structured report with citations.

Strategy:
1. Start by searching the web for the topic to get an overview.
2. Fetch the most promising URLs to get detailed information.
3. Use analyze_data to extract key insights when you have large amounts of text.
4. Repeat searches with refined queries if needed.
5. Once you have enough information, produce a final report.

Report format:
- Use clear sections with headers.
- Cite every claim with [Source Title](URL).
- Include a References section at the end listing all URLs used.
- Be comprehensive but concise."""

# ---------------------------------------------------------------------------
# Step 1: Tool declarations for Gemini
# ---------------------------------------------------------------------------
TOOLS = genai.protos.Tool(
    function_declarations=[
        genai.protos.FunctionDeclaration(
            name="web_search",
            description="Search the web for current information on a topic. Returns search results with titles, URLs, and snippets.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "query": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="The search query",
                    ),
                    "max_results": genai.protos.Schema(
                        type=genai.protos.Type.INTEGER,
                        description="Maximum number of results to return (1-10)",
                    ),
                },
                required=["query"],
            ),
        ),
        genai.protos.FunctionDeclaration(
            name="fetch_url",
            description="Fetch the text content of a web page. Returns main text content stripped of HTML.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "url": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="The URL to fetch",
                    ),
                },
                required=["url"],
            ),
        ),
        genai.protos.FunctionDeclaration(
            name="analyze_data",
            description="Analyze and extract structured insights from raw text data based on a specific focus area.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "content": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="The text content to analyze",
                    ),
                    "focus": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="The specific aspect or question to focus the analysis on",
                    ),
                },
                required=["content", "focus"],
            ),
        ),
    ]
)

# ---------------------------------------------------------------------------
# Step 2: Tool executors
# ---------------------------------------------------------------------------

async def execute_web_search(args: dict) -> str:
    """Call SerpAPI and return formatted results."""
    query = args.get("query", "")
    max_results = min(int(args.get("max_results", 5)), 10)
    api_key = os.environ.get("SERPAPI_API_KEY", "")

    if not api_key:
        return "Error: SERPAPI_API_KEY environment variable is not set."

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            "https://serpapi.com/search",
            params={
                "q": query,
                "num": max_results,
                "api_key": api_key,
                "engine": "google",
            },
        )
        response.raise_for_status()
        data = response.json()

    results = data.get("organic_results", [])
    if not results:
        return f"No results found for: {query}"

    formatted = []
    for r in results[:max_results]:
        formatted.append(
            f"Title: {r.get('title', 'N/A')}\n"
            f"URL: {r.get('link', 'N/A')}\n"
            f"Snippet: {r.get('snippet', 'N/A')}"
        )
    return "\n\n".join(formatted)


async def execute_fetch_url(args: dict) -> str:
    """Fetch a URL and return clean text content."""
    url = args.get("url", "")

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove non-content elements
    for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    # Truncate to ~8000 chars to stay within token limits
    if len(text) > 8000:
        text = text[:8000] + "\n\n[Content truncated...]"

    return text


async def execute_analyze_data(args: dict) -> str:
    """Extract key points from content based on a focus area."""
    content = args.get("content", "")
    focus = args.get("focus", "")

    # Truncate content if too long
    if len(content) > 4000:
        content = content[:4000] + "..."

    lines = content.split("\n")
    # Filter for non-empty lines
    lines = [line.strip() for line in lines if line.strip()]

    return (
        f"Analysis focus: {focus}\n\n"
        f"Content ({len(lines)} lines):\n"
        + "\n".join(f"- {line}" for line in lines[:50])
    )


# Tool router
EXECUTORS = {
    "web_search": execute_web_search,
    "fetch_url": execute_fetch_url,
    "analyze_data": execute_analyze_data,
}


async def execute_tool(name: str, args: dict) -> str:
    """Route to the correct tool executor. Never raises — returns error strings."""
    executor = EXECUTORS.get(name)
    if executor is None:
        return f"Unknown tool: {name}"
    try:
        return await executor(args)
    except Exception as e:
        return f"Error executing {name}: {e}"


# ---------------------------------------------------------------------------
# Step 3: Agent loop
# ---------------------------------------------------------------------------

async def _send_with_retry(chat, message, max_retries: int = 3):
    """Send a message to Gemini with exponential backoff on rate limits."""
    for attempt in range(max_retries + 1):
        try:
            return await asyncio.to_thread(chat.send_message, message)
        except ResourceExhausted as e:
            if attempt == max_retries:
                raise
            wait = 2 ** attempt * 2  # 2s, 4s, 8s
            logger.warning(f"Rate limited, retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(wait)


async def run_agent(topic: str, max_iterations: int = 15) -> dict:
    """Run the research agent loop and return a report with metadata."""
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

    model = genai.GenerativeModel(
        "gemini-2.0-flash",
        tools=[TOOLS],
        system_instruction=SYSTEM_PROMPT,
    )

    chat = model.start_chat()
    prompt = f"Research the following topic and produce a comprehensive report with citations: {topic}"

    # Send initial message with retry
    response = await _send_with_retry(chat, prompt)

    tool_calls_log: list[dict] = []
    iterations = 0

    for iteration in range(max_iterations):
        iterations = iteration + 1

        # Check for function calls in the response
        function_calls = [
            part
            for part in response.candidates[0].content.parts
            if part.function_call.name
        ]

        # No function calls → we have the final text response
        if not function_calls:
            try:
                report = response.text
            except ValueError:
                report = "The agent did not produce a final text report."
            return {
                "report": report,
                "tool_calls": tool_calls_log,
                "iterations": iterations,
            }

        # Execute each function call and build response parts
        function_responses = []
        for fc in function_calls:
            name = fc.function_call.name
            args = dict(fc.function_call.args)

            result = await execute_tool(name, args)

            tool_calls_log.append({
                "tool": name,
                "args": {k: v[:200] if isinstance(v, str) and len(v) > 200 else v for k, v in args.items()},
                "result_preview": result[:300] if len(result) > 300 else result,
            })

            function_responses.append(
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=name,
                        response={"result": result},
                    )
                )
            )

        # Send function responses back to Gemini with retry
        response = await _send_with_retry(chat, function_responses)

    # Max iterations exhausted
    return {
        "report": "Research timed out: maximum iterations reached without a final response.",
        "tool_calls": tool_calls_log,
        "iterations": iterations,
    }
