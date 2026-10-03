r"""The Phase 4 runtime: router -> retrieval -> guardrail -> LangGraph (Node 1 <-> Node 2).

    route(offence_date)                       Stage 0, a plain function
    ranker.rank_sections(facts, era)          retrieval, query encoded on CPU
    guardrail.check(...)                      insufficient data -> return, no LLM
    embedder.free()                           the 4GB card is Ollama's from here
    StateGraph:
        statute_identifier (Node 1) -> verifier (Node 2)
        verifier --(unconfirmed and retry_count < 2)--> statute_identifier
        verifier --(otherwise)--> END

The VRAM handoff (CLAUDE.md Section 2): the 4GB card holds either BGE-M3 or
qwen3.5:4b, never both, and Ollama keeps its model resident for minutes after a
call. So the query is encoded on the GPU only after llm.unload() has evicted the
model; embedder.free() then returns the card before Node 1 reloads it. If the
card is still short (another process holds it), encoding falls back to CPU.
PRAMANA_RUNTIME_DEVICE=cpu restores the CPU-only path.
"""
from __future__ import annotations

import os
import re
import time
from functools import partial

from src.graph import citation_graph as cg
from src.retrieval import embedder, ranker

from . import ablation, applicability, chargeability, guardrail, llm as llm_mod, nodes
from .router import STRADDLE_WARNING, route, route_period
from .state import initial_state

TOP_K_CANDIDATES = 10
EXCERPT_CHARS = 300
RUNTIME_DEVICE = os.environ.get("PRAMANA_RUNTIME_DEVICE", "cuda").strip().lower()
REVIEW_CANDIDATES = 5

_graph = None


def citation_graph():
    global _graph
    if _graph is None:
        _graph = cg.load()
    return _graph


def build_graph(llm, g, text_of=None, check_applicability=True):
    """Node 1 <-> Node 2 retry loop, then Node 2b (applicability) once the loop ends.

    Node 2b runs after the loop, not inside it: the retry loop is about
    citations that do not EXIST, and its cap (retry_count < 2) is unchanged.
    `check_applicability=False` reproduces the Phase 4 graph exactly."""
    from langgraph.graph import END, START, StateGraph

    from .state import PipelineState

    sg = StateGraph(PipelineState)
    sg.add_node("statute_identifier", partial(nodes.statute_identifier, llm=llm))
    sg.add_node("verifier", partial(nodes.verifier, g=g))
    sg.add_edge(START, "statute_identifier")
    sg.add_edge("statute_identifier", "verifier")
    after = "applicability" if check_applicability else END
    if check_applicability:
        sg.add_node("applicability", partial(applicability.assess, llm=llm,
                                             text_of=text_of or applicability.statute_text))
        sg.add_edge("applicability", END)
    sg.add_conditional_edges("verifier", nodes.route_after_verify,
                             {"statute_identifier": "statute_identifier", "end": after})
    return sg.compile()


def _excerpt(text):
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= EXCERPT_CHARS else t[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " ..."


def retrieve_candidates(case_facts, era, cli=None, device=RUNTIME_DEVICE):
    exclude = None if ablation.off("exclude") else chargeability.non_chargeable_sections(era)
    rows = ranker.rank_sections(case_facts, era, top_k=TOP_K_CANDIDATES, cli=cli, device=device,
                                exclude=exclude)
    if not ablation.off("dual"):
        # Two lists, not one. Precedent votes are a popularity prior: they put
        # the right section in the top 3 more often (dev 11/15 vs 9/15 by
        # statute text alone) but crowd out sections the facts match textually
        # (dev top-10: fused 13/15, statute text 14/15; held-out 3 #10, a
        # threat with an axe, got attempt to murder and murder on top). The
        # fused top 10 comes first, then the statute-text top 10's new sections.
        seen = {r["section"] for r in rows}
        for r in ranker.rank_sections(case_facts, era, top_k=TOP_K_CANDIDATES, cli=cli,
                                      device=device, exclude=exclude, use_votes=False):
            if r["section"] not in seen:
                rows.append(r)
                seen.add(r["section"])
    for r in rows:
        r["excerpt"] = _excerpt(ranker._section_record(era, r["section"]).get("text"))
    return rows


def run(case_facts, offence_date, llm=None, g=None, cli=None, retrieve=None, sufficient=None,
        text_of=None, check_applicability=True, offence_date_to=None):
    """One case through the pipeline. Returns a dict with `status`, the final
    state (Section 3 fields + additions), `charges` (verified AND supported by
    Node 2b), `unsupported` (verified but not shown to apply), and timings.

    `offence_date_to` makes the offence a period. If the period straddles the
    IPC->BNS transition, the pipeline runs once per code and returns
    {"status": "straddles_transition", "runs": {"ipc": ..., "bns": ...},
    "warnings": [...]}: each run is dated on its own side of the line.

    `llm`, `g`, `retrieve`, `sufficient` and `text_of` are injectable so tests
    run with no Ollama, no index and no GPU.
    """
    check_applicability = check_applicability and not ablation.off("judge")
    kw = dict(llm=llm, g=g, cli=cli, retrieve=retrieve, sufficient=sufficient, text_of=text_of,
              check_applicability=check_applicability)
    if offence_date_to is not None:
        eras = route_period(offence_date, offence_date_to)
        if len(eras) == 2:
            runs = {"ipc": _run_one(case_facts, offence_date, **kw),
                    "bns": _run_one(case_facts, offence_date_to, **kw)}
            for r in runs.values():
                r["state"]["warnings"].append(STRADDLE_WARNING)
            return {"status": "straddles_transition", "runs": runs, "warnings": [STRADDLE_WARNING]}
        # One side only: date the run by the period's end, which is on that side.
        return _run_one(case_facts, offence_date_to, **kw)
    return _run_one(case_facts, offence_date, **kw)


def _review(retrieved, n):
    return [{"section": r["section"], "matched": r.get("matched"), "title": r.get("title")}
            for r in retrieved[:n]]


def _encode_device(uses_embedder=True):
    """Where this run encodes its query: the GPU, after Ollama has let go of it."""
    if RUNTIME_DEVICE != "cuda" or not uses_embedder:
        return "cpu"
    import torch

    if not torch.cuda.is_available():
        return "cpu"
    llm_mod.unload()
    return "cuda"


def _on_device(fn, device):
    """fn(device); on a CUDA out-of-memory error, free the card and redo it on CPU."""
    if device != "cuda":
        return fn("cpu")
    import torch

    try:
        return fn("cuda")
    except torch.cuda.OutOfMemoryError:
        embedder.free()
        return fn("cpu")


def _run_one(case_facts, offence_date, llm=None, g=None, cli=None, retrieve=None, sufficient=None,
             text_of=None, check_applicability=True):
    timings = {}
    t0 = time.perf_counter()
    era = route(offence_date)
    timings["route_s"] = time.perf_counter() - t0

    t = time.perf_counter()
    device = _encode_device(uses_embedder=sufficient is None or retrieve is None)
    timings["unload_s"] = time.perf_counter() - t

    t = time.perf_counter()
    if sufficient is None:
        ok, detail = _on_device(lambda d: guardrail.check(case_facts, era, cli=cli, device=d), device)
    else:
        ok, detail = sufficient(case_facts, era)
    timings["guardrail_s"] = time.perf_counter() - t
    if not ok:
        # No LLM call on weak context (CLAUDE.md Section 2) -- but never a bare
        # refusal either. The guardrail's signal is judgment similarity, which
        # measures CORPUS COVERAGE, not whether the facts allege a crime: held-out
        # 3 #7 (a contractor smashing a water meter, mischief) scored 0.555,
        # below the cricket text in the calibration set (0.557). So the nearest
        # statute sections are still shown, labelled as unverified retrieval.
        t = time.perf_counter()
        review = [] if not case_facts or not case_facts.strip() else (
            retrieve(case_facts, era) if retrieve else _on_device(
                lambda d: retrieve_candidates(case_facts, era, cli=cli, device=d), device))
        timings["retrieve_s"] = time.perf_counter() - t
        embedder.free()
        return {"status": "insufficient_data", "era": era, "guardrail": detail,
                "state": initial_state(case_facts, offence_date, era, review), "timings": timings,
                "review_candidates": _review(review, TOP_K_CANDIDATES),
                "charges": [], "unsupported": [], "doubted": []}

    t = time.perf_counter()
    retrieved = retrieve(case_facts, era) if retrieve else _on_device(
        lambda d: retrieve_candidates(case_facts, era, cli=cli, device=d), device)
    timings["retrieve_s"] = time.perf_counter() - t
    embedder.free()

    graph = build_graph(llm or llm_mod.chat_json, g if g is not None else citation_graph(),
                        text_of=text_of, check_applicability=check_applicability)
    t = time.perf_counter()
    final = graph.invoke(initial_state(case_facts, offence_date, era, retrieved))
    timings["graph_s"] = time.perf_counter() - t

    if final["verified_sections"]:
        status = "ok"
    elif final["candidate_sections"]:
        status = "no_verified_sections"
    else:
        status = "no_proposals"
    # Never a bare "nothing found": with no verified section, the closest
    # retrieved sections are surfaced for the lawyer to review. They are
    # retrieval results from the ingested statutes, labelled as such -- not
    # verified charges.
    review = [] if final["verified_sections"] else _review(final["retrieved"], REVIEW_CANDIDATES)
    return {"status": status, "era": era, "guardrail": detail, "state": final, "timings": timings,
            "review_candidates": review, **split_by_applicability(final, check_applicability)}


# Node 2b is ADVISORY, not a gate (decided 2026-09-30 on the dev-set ablation):
# as a gate it cut extra sections by a third but removed the right charge in 4
# of 15 cases (charges recall 14 -> 10), for a precision gain of 38% -> 42%.
# So every verified section is a charge, and the judge's doubts travel beside
# it (`doubted`, with the missing ingredient it named) for the report to show.
# JUDGE_GATES = True restores the gate for comparison.
JUDGE_GATES = False


def split_by_applicability(state, checked=True, gates=None):
    """charges, unsupported (only when the judge gates) and doubted.

    doubted = verified sections the judge did not support, each with its reason;
    advisory -- never removed from charges unless `gates`."""
    gates = JUDGE_GATES if gates is None else gates
    if not checked:
        return {"charges": list(state["verified_sections"]), "unsupported": [], "doubted": []}
    ok = {(a["section"], a["subsection"]) for a in state["applicability"] if a["supported"]}
    why = {(a["section"], a["subsection"]): a.get("rule_rejected") or a.get("missing_ingredient") or ""
           for a in state["applicability"]}
    doubted = [{**v, "doubt": why.get((v["section"], v["subsection"]), "")}
               for v in state["verified_sections"] if (v["section"], v["subsection"]) not in ok]
    if not gates:
        return {"charges": list(state["verified_sections"]), "unsupported": [], "doubted": doubted}
    charges = [v for v in state["verified_sections"] if (v["section"], v["subsection"]) in ok]
    return {"charges": charges, "unsupported": [d for d in doubted], "doubted": doubted}
