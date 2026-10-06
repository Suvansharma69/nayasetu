r"""FastAPI backend: the full pipeline, and the chat-style web interface (Phase 7).

    GET  /                  the web interface (app/web/index.html)
    POST /analyze           {"facts", "offence_date": "YYYY-MM-DD", "offence_date_to"?} -> report
    POST /jobs              same body; starts the analysis in the background -> {"id"}
    GET  /jobs/{id}         {"state": running|done|error, "stages": [...], "report"?, "error"?}
    POST /dates             {"text"} -> the offence dates written in it, each with its code
    GET  /samples           the demo cases;  GET /samples/{id}  a saved report
    GET  /section/{code}/{s}  bare-act text, punishment, classification, counterpart (graph-checked)
    GET  /compare/{code}/{s}  IPC <-> BNS side by side with a word diff (verified mapping)
    POST /pdf               raw PDF bytes -> its text (digital PDFs; no OCR)
    POST /ask               {"report", "question", "history"?} -> grounded answer, citations checked
    POST /summarise         {"doc_id"} -> headnote of an ingested judgment, quote checked verbatim
    GET  /health            Ollama reachable? graph and outcomes table present?

One analysis at a time: the 4GB card holds either BGE-M3 or the LLM, and the
pipeline hands it between them (CLAUDE.md Section 2), so concurrent runs would
fight over it. A second request waits for the first (a job reports "queued").

Run:  venv\Scripts\python.exe -m uvicorn src.api.main:app --port 8000
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402


from src.api import assistant, dates, lawtools, report  # noqa: E402
from src.pipeline import analytics, graph, llm, progress, router  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "app" / "samples"
WEB = ROOT / "app" / "web" / "index.html"
MAX_JOBS = 20

app = FastAPI(title="Pramana", description="AI-assisted legal research for Indian criminal law")
_lock = threading.Lock()
_jobs: dict[str, dict] = {}


class Case(BaseModel):
    facts: str = Field(min_length=20, max_length=12000)   # a pasted FIR/order; intake reduces it
    offence_date: str
    offence_date_to: str | None = None


class Text(BaseModel):
    text: str = Field(max_length=12000)


class Question(BaseModel):
    report: dict
    question: str = Field(min_length=3, max_length=600)
    history: list[list[str]] = Field(default_factory=list, max_length=6)


class DocId(BaseModel):
    doc_id: str = Field(min_length=1, max_length=200)


def _check_dates(case):
    try:
        router.route(case.offence_date)
        if case.offence_date_to:
            router.route_period(case.offence_date, case.offence_date_to)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _run(case):
    """The pipeline under the GPU lock -> report. Raises HTTPException."""
    with _lock:
        try:
            res = graph.run(case.facts, case.offence_date, offence_date_to=case.offence_date_to, full=True)
        except llm.LLMError as e:
            raise HTTPException(status_code=503, detail=f"local model unavailable: {e}") from e
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    return report.build(res)


@app.get("/", include_in_schema=False)
def web():
    return FileResponse(WEB)


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
    # A plain `def` endpoint runs in FastAPI's threadpool, so waiting here does
    # not block /health.
    _check_dates(case)
    return _run(case)


@app.post("/jobs")
def start_job(case: Case):
    _check_dates(case)
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "state": "queued", "stages": [], "started": time.time()}
    _jobs[jid] = job
    for old in sorted(_jobs, key=lambda k: _jobs[k]["started"])[:-MAX_JOBS]:
        _jobs.pop(old, None)

    def on_stage(ev):
        job["state"] = "running"
        job["stages"].append({**ev, "label": progress.STAGES.get(ev["stage"], ev["stage"]),
                              "at": round(time.time() - job["started"], 1)})

    def work():
        try:
            with progress.listening(on_stage):
                job["report"] = _run(case)
            job["state"] = "done"
        except HTTPException as e:
            job.update(state="error", error=e.detail)
        except Exception as e:  # noqa: BLE001 -- shown to the user, not swallowed
            job.update(state="error", error=f"{type(e).__name__}: {e}")
        job["elapsed"] = round(time.time() - job["started"], 1)

    threading.Thread(target=work, daemon=True).start()
    return {"id": jid}


@app.get("/jobs/{jid}")
def job_status(jid: str):
    job = _jobs.get(jid)
    if job is None:
        raise HTTPException(status_code=404, detail="no such job (the server may have restarted)")
    return {**job, "elapsed": job.get("elapsed", round(time.time() - job["started"], 1))}


@app.post("/dates")
def read_dates(body: Text):
    """Offence dates written in the text. Never a guess: the page asks the user
    when there are none, several, or only a month (src/api/dates.py)."""
    found = dates.find_dates(body.text)
    for d in found["dates"]:
        try:
            d["era"] = router.route(d["date"])
        except ValueError as e:  # in the future
            d["era"], d["error"] = None, str(e)
    return {**found, "transition": router.transition_date().isoformat()}


@app.get("/samples")
def samples():
    cases = json.loads((SAMPLES / "cases.json").read_text(encoding="utf-8"))
    return [{**c, "saved": (SAMPLES / f"{c['id']}.json").exists()} for c in cases]


@app.get("/samples/{sid}")
def sample(sid: str):
    ids = {c["id"] for c in json.loads((SAMPLES / "cases.json").read_text(encoding="utf-8"))}
    path = SAMPLES / f"{sid}.json"
    if sid not in ids or not path.exists():
        raise HTTPException(status_code=404, detail="no saved report for that sample")
    return json.loads(path.read_text(encoding="utf-8"))


# --- lawyer tools ------------------------------------------------------------------

MAX_PDF_BYTES, MAX_PDF_PAGES, MAX_PDF_CHARS = 20_000_000, 60, 12000


@app.get("/section/{code}/{section}")
def section(code: str, section: str):
    info = lawtools.section_info(graph.citation_graph(), code, section)
    if info is None:
        raise HTTPException(status_code=404, detail=f"{code.upper()} {section} is not a section of the ingested {code.upper()}")
    return info


@app.get("/compare/{code}/{section}")
def compare(code: str, section: str):
    out = lawtools.compare(graph.citation_graph(), code, section)
    if out is None:
        raise HTTPException(status_code=404, detail=f"{code.upper()} {section} is not a section of the ingested {code.upper()}")
    return out


@app.post("/pdf")
async def pdf(request: Request):
    """The text of an uploaded PDF, read locally. A scanned PDF has no text layer
    (no OCR here), and says so instead of returning nothing."""
    data = await request.body()
    if not data:
        raise HTTPException(status_code=422, detail="empty upload")
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF larger than 20 MB")
    import pymupdf

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"not a readable PDF: {e}") from e
    pages = len(doc)
    raw = "\n".join(doc[i].get_text() for i in range(min(pages, MAX_PDF_PAGES)))
    text = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return {"text": text[:MAX_PDF_CHARS], "pages": pages, "chars": len(text),
            "truncated": len(text) > MAX_PDF_CHARS or pages > MAX_PDF_PAGES,
            "scanned": len(text) < 40 * min(pages, 3)}


@app.post("/ask")
def ask(q: Question):
    if q.report.get("era") not in assistant.ERAS:
        raise HTTPException(status_code=422, detail="report has no valid era")
    with _lock:   # shares the GPU with analyses
        try:
            return assistant.ask(q.report, q.question, llm.chat_json, graph.citation_graph(),
                                 [tuple(h[:2]) for h in q.history if len(h) >= 2])
        except llm.LLMError as e:
            raise HTTPException(status_code=503, detail=f"local model unavailable: {e}") from e


@app.post("/summarise")
def summarise(body: DocId):
    with _lock:
        try:
            return assistant.summarise(body.doc_id, llm.chat_json, graph.citation_graph())
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except llm.LLMError as e:
            raise HTTPException(status_code=503, detail=f"local model unavailable: {e}") from e
