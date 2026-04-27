"""FastAPI application — webhook handler for ai-pr-audit."""

from fastapi import FastAPI

from ai_pr_audit import __version__

app = FastAPI(title="ai-pr-audit", version=__version__)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
