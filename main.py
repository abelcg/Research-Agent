import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent import run_agent

logging.basicConfig(level=logging.INFO)

load_dotenv()

app = FastAPI(title="Research Agent API")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ResearchRequest(BaseModel):
    topic: str
    max_iterations: int = Field(default=15, ge=1, le=30)


class ResearchResponse(BaseModel):
    report: str
    tool_calls_count: int
    iterations: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/research", response_model=ResearchResponse)
async def research(request: ResearchRequest):
    try:
        result = await run_agent(request.topic, request.max_iterations)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent error: {e}")
    return ResearchResponse(
        report=result["report"],
        tool_calls_count=len(result["tool_calls"]),
        iterations=result["iterations"],
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
