r"""The Phase 4 runtime: router -> retrieval -> guardrail -> LangGraph (Node 1 <-> Node 2).

    route(offence_date)                       Stage 0, a plain function
    ranker.rank_sections(facts, era)          retrieval, query encoded on CPU
    guardrail.check(...)                      insufficient data -> return, no LLM
    embedder.free()                           the 4GB card is Ollama's from here
    StateGraph:
        statute_identifier (Node 1) -> verifier (Node 2)
        verifier --(unconfirmed and retry_count < 2)--> statute_identifier
        verifier --(otherwise)--> END

Why CPU encoding at runtime: Ollama keeps qwen3.5:4b resident for minutes after
a call, so the NEXT query's embedder, loaded onto the GPU, would land beside it
on a 4GB card. One query on CPU is sub-second once the model is loaded. GPU
stays the bulk-indexing path (scripts/build_index.py).
"""
from __future__ import annotations

import re
import time
from functools import partial

from src.graph import citation_graph as cg
from src.retrieval import embedder, ranker

from . import guardrail, llm as llm_mod, nodes
from .router import route
from .state import initial_state

TOP_K_CANDIDATES = 10
EXCERPT_CHARS = 300
RUNTIME_DEVICE = "cpu"

_graph = None


def citation_graph():
    global _graph
    if _graph is None:
        _graph = cg.load()
    return _graph


def build_graph(llm, g):
    from langgraph.graph import END, START, StateGraph

    from .state import PipelineState

    sg = StateGraph(PipelineState)
    sg.add_node("statute_identifier", partial(nodes.statute_identifier, llm=llm))
    sg.add_node("verifier", partial(nodes.verifier, g=g))
    sg.add_edge(START, "statute_identifier")
    sg.add_edge("statute_identifier", "verifier")
    sg.add_conditional_edges("verifier", nodes.route_after_verify,
                             {"statute_identifier": "statute_identifier", "end": END})
    return sg.compile()


def _excerpt(text):
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= EXCERPT_CHARS else t[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " ..."


def retrieve_candidates(case_facts, era, cli=None, device=RUNTIME_DEVICE):
    rows = ranker.rank_sections(case_facts, era, top_k=TOP_K_CANDIDATES, cli=cli, device=device)
    for r in rows:
        r["excerpt"] = _excerpt(ranker._section_record(era, r["section"]).get("text"))
    return rows


def run(case_facts, offence_date, llm=None, g=None, cli=None, retrieve=None, sufficient=None):
    """One case through Phase 4. Returns a dict with `status`, the final state
    (Section 3 fields + era/retrieved/unconfirmed) and per-stage timings.

    `llm`, `g`, `retrieve` and `sufficient` are injectable so tests run with no
    Ollama, no index and no GPU.
    """
    timings = {}
    t0 = time.perf_counter()
    era = route(offence_date)
    timings["route_s"] = time.perf_counter() - t0

    t = time.perf_counter()
    if sufficient is None:
        ok, detail = guardrail.check(case_facts, era, cli=cli)
    else:
        ok, detail = sufficient(case_facts, era)
    timings["guardrail_s"] = time.perf_counter() - t
    if not ok:
        embedder.free()
        return {"status": "insufficient_data", "era": era, "guardrail": detail,
                "state": initial_state(case_facts, offence_date, era, []), "timings": timings}

    t = time.perf_counter()
    retrieved = retrieve(case_facts, era) if retrieve else retrieve_candidates(case_facts, era, cli=cli)
    timings["retrieve_s"] = time.perf_counter() - t
    embedder.free()

    graph = build_graph(llm or llm_mod.chat_json, g if g is not None else citation_graph())
    t = time.perf_counter()
    final = graph.invoke(initial_state(case_facts, offence_date, era, retrieved))
    timings["graph_s"] = time.perf_counter() - t

    if final["verified_sections"]:
        status = "ok"
    elif final["candidate_sections"]:
        status = "no_verified_sections"
    else:
        status = "no_proposals"
    return {"status": status, "era": era, "guardrail": detail, "state": final, "timings": timings}
