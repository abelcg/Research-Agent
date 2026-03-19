# Research Agent API

A multi-step research agent powered by **Google Gemini 2.0 Flash** that autonomously searches the web, fetches pages, analyzes content, and produces structured reports with citations.

Built as part of **Lab 02: Multi-Step Agent with Tool Use**.

## Architecture

```
                    +───────────────────────────────────────+
                    │         Agent Loop                    │
POST /research ──>  │                                       │
  { topic }         │  ┌─────────┐    ┌──────────────┐      │
                    │  │ Gemini  │───>│ Tool Router  │      │
                    │  │ API     │<───│              │      │
                    │  └─────────┘    └──────┬───────┘      │
                    │                        │              │
                    │        ┌───────────────┼──────┐       │
                    │        v               v      v       │
                    │  [web_search]  [fetch_url] [analyze]  │
                    │                                       │
                    +───────────────────────────────────────+
                                     │
                                     v
                              Structured Report
```

**Agent loop flow:**

1. User sends a research topic via `POST /research`
2. Gemini receives the topic and decides which tools to call
3. The agent executes tool calls and sends results back to Gemini
4. Gemini processes results and may request more tool calls
5. Loop repeats until Gemini produces a final text report (or max iterations reached)

## Tools

| Tool | Description | External API |
|------|-------------|-------------|
| `web_search` | Searches the web for current information. Returns titles, URLs, and snippets. | [SerpAPI](https://serpapi.com/) |
| `fetch_url` | Fetches a web page and extracts clean text content (strips HTML, scripts, styles, nav, footer, header). Truncates to 8000 chars. | Direct HTTP |
| `analyze_data` | Extracts structured insights from raw text based on a focus area. | Local processing |

## Tech Stack

- **Language:** Python 3.10+
- **AI Model:** Google Gemini 2.0 Flash (via `google-generativeai` SDK)
- **Web Framework:** FastAPI + Uvicorn
- **HTTP Client:** httpx (async)
- **HTML Parsing:** BeautifulSoup4
- **Search API:** SerpAPI (Google search engine)
- **Package Manager:** uv
- **Deployment:** Docker + Render

## Project Structure

```
research-agent/
├── agent.py          # Tool definitions, executors, and agent loop
├── main.py           # FastAPI app with /research and /health endpoints
├── pyproject.toml    # Dependencies and project metadata (uv)
├── uv.lock           # Locked dependency versions
├── Dockerfile        # Container definition for deployment
├── render.yaml       # Render deployment configuration
├── .env.example      # Template for required environment variables
└── README.md
```

## Prerequisites

- **Python 3.10+** installed
- **[uv](https://docs.astral.sh/uv/)** package manager installed
- **Google AI API key** — free tier available at [aistudio.google.com](https://aistudio.google.com)
- **SerpAPI key** — free tier (100 searches/month) at [serpapi.com](https://serpapi.com/)

---

## Installation

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd research-agent
```

### 2. Install dependencies

```bash
uv sync
```

This creates a virtual environment in `.venv/` and installs all dependencies from `uv.lock`.

### 3. Configure environment variables

Copy the example file and fill in your API keys:

```bash
cp .env.example .env
```

Edit `.env`:

```env
GOOGLE_API_KEY=your-google-ai-api-key
SERPAPI_API_KEY=your-serpapi-api-key
```

---

## Running Locally

### Start the server

```bash
uv run python main.py
```

The API starts on `http://localhost:8000` by default. Override the port with the `PORT` environment variable.

### Test the health endpoint

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "ok"}
```

### Run a research query

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"topic": "Current state of WebAssembly adoption"}'
```

With custom max iterations:

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"topic": "Rust vs Go for backend development", "max_iterations": 10}'
```

Expected response:

```json
{
  "report": "# Rust vs Go for Backend Development\n\n## Overview\n...",
  "tool_calls_count": 7,
  "iterations": 5
}
```

### Interactive API docs

FastAPI provides auto-generated documentation:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## API Reference

### `GET /health`

Health check endpoint.

**Response:** `200 OK`

```json
{"status": "ok"}
```

### `POST /research`

Run the research agent on a given topic.

**Request body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `topic` | string | yes | — | The research topic |
| `max_iterations` | integer | no | 15 | Max agent loop iterations (1–30) |

**Response:** `200 OK`

```json
{
  "report": "string — the full research report with citations",
  "tool_calls_count": 7,
  "iterations": 5
}
```

**Error response:** `502 Bad Gateway`

```json
{
  "detail": "Agent error: <error message>"
}
```

---

## Deployment to Render

### 1. Push to GitHub

```bash
git add -A
git commit -m "Initial research agent implementation"
git remote add origin <your-repo-url>
git push -u origin main
```

### 2. Create a new Web Service on Render

1. Go to [dashboard.render.com](https://dashboard.render.com)
2. Click **New** > **Web Service**
3. Connect your GitHub repository
4. Render will auto-detect the `render.yaml` configuration

### 3. Set environment variables

In the Render dashboard, add the following environment variables:

| Variable | Value |
|----------|-------|
| `GOOGLE_API_KEY` | Your Google AI API key |
| `SERPAPI_API_KEY` | Your SerpAPI key |

The `PORT` variable is already set to `8000` in `render.yaml`.

### 4. Deploy

Render will automatically build the Docker image and deploy. The first deploy takes a few minutes.

### 5. Test the deployed service

```bash
# Health check
curl https://your-app.onrender.com/health

# Research query
curl -X POST https://your-app.onrender.com/research \
  -H "Content-Type: application/json" \
  -d '{"topic": "Current state of WebAssembly adoption"}'
```

---

## Key Implementation Details

### Agent Loop

The core loop in `agent.py:run_agent()` follows the Gemini function calling pattern:

1. Send initial prompt to Gemini
2. Check response for `function_call` parts
3. If no function calls → return the text as the final report
4. If function calls exist → execute each tool, build `function_response` parts, send back to Gemini
5. Repeat until a final text response or max iterations

### Retry with Exponential Backoff

The `_send_with_retry()` function handles Gemini API rate limits (`ResourceExhausted` / 429 errors) with exponential backoff: 2s, 4s, 8s waits across up to 3 retries.

### Error Handling

- **Tool executors** never raise exceptions — errors are returned as strings so Gemini can adapt its strategy.
- **Agent loop** errors bubble up to the FastAPI endpoint, which returns a `502` with the error detail.
- **Unknown tools** return `"Unknown tool: <name>"` instead of crashing.

### Async Architecture

- Tool executors (`web_search`, `fetch_url`, `analyze_data`) are fully async using `httpx.AsyncClient`.
- Gemini SDK calls are synchronous, so they are offloaded to a thread via `asyncio.to_thread()` to avoid blocking the FastAPI event loop.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_API_KEY` | Yes | Google AI Studio API key for Gemini |
| `SERPAPI_API_KEY` | Yes | SerpAPI key for web search |
| `PORT` | No | Server port (default: `8000`) |
