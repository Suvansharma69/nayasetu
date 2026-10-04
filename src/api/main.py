r"""FastAPI backend: the full pipeline behind one endpoint (Phase 7).

    POST /analyze   {"facts": str, "offence_date": "YYYY-MM-DD", "offence_date_to": optional}
    GET  /health    Ollama reachable? graph and outcomes table present?

One analysis at a time: the 4GB card holds either BGE-M3 or the LLM, and the
pipeline hands it between them (CLAUDE.md Section 2), so concurrent runs would
fight over it. A second request waits for the first.

Run:  venv\Scripts\python.exe -m uvicorn src.api.main:app --port 8000
"""
from __future__ import annotations

import os
import threading

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from src.api import report  # noqa: E402
from src.pipeline import analytics, graph, llm, router  # noqa: E402

app = FastAPI(title="Pramana", description="AI-assisted legal research for Indian criminal law")
_lock = threading.Lock()


class Case(BaseModel):
    facts: str = Field(min_length=20, max_length=5000)
    offence_date: str
    offence_date_to: str | None = None


@app.get("/health")
def health():
    import httpx

    try:
        ollama = httpx.get(f"{llm.host()}/api/tags", timeout=3).status_code == 200
    except httpx.HTTPError:
        ollama = False
    return {"ollama": ollama, "model": llm.model(),
            "graph": os.path.exists(graph.cg.graph_path()), "outcomes": analytics.DB_PATH.exists()}


@app.post("/analyze")
def analyze(case: Case):
    try:
        router.parse_date(case.offence_date)
        if case.offence_date_to:
            router.parse_date(case.offence_date_to)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    # A plain `def` endpoint runs in FastAPI's threadpool, so waiting here does
    # not block /health.
    with _lock:
        try:
            res = graph.run(case.facts, case.offence_date, offence_date_to=case.offence_date_to, full=True)
        except llm.LLMError as e:
            raise HTTPException(status_code=503, detail=f"local model unavailable: {e}") from e
        except ValueError as e:  # e.g. an offence date in the future (router)
            raise HTTPException(status_code=422, detail=str(e)) from e
    return report.build(res)
