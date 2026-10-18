r"""The pipeline result -> the JSON report the API returns and the frontend draws.

Verified and unconfirmed citations are kept in separate fields, so the report
can never render them alike (CLAUDE.md Section 3).
"""
from __future__ import annotations

ERA_NAME = {"ipc": "Indian Penal Code, 1860 (offence before 1 July 2024)",
            "bns": "Bharatiya Nyaya Sanhita, 2023 (offence on/after 1 July 2024)"}
RETRIEVED_KEPT = 14  # graph._brief's default: what the live view shows
RANK_KEYS = ("score", "statute_rank", "statute_score", "vote_rank", "list")


def brief_row(r):
    """A retrieved candidate with the signals that ranked it (as graph.brief_row)."""
    return {"section": r["section"], "ref": r.get("matched") or r["section"], "title": r.get("title"),
            **{k: r[k] for k in RANK_KEYS if r.get(k) is not None}}


def _charge(v, doubt=None):
    return {"code": None, "section": v["section"], "subsection": v.get("subsection"),
            "title": v.get("title"), "reason": v.get("reason"), "doubt": doubt}


def build(result):
    """One report per run; a period straddling 1 July 2024 gives one per code."""
    if result.get("status") == "straddles_transition":
        return {"status": "straddles_transition", "warnings": result.get("warnings", []),
                "runs": {era: build(r) for era, r in result["runs"].items()}}
    st = result["state"]
    era = result["era"]
    doubts = {(d["section"], d.get("subsection")): d.get("doubt") for d in result.get("doubted", [])}
    charges = []
    for v in result.get("charges", []):
        c = _charge(v, doubts.get((v["section"], v.get("subsection"))))
        c["code"] = era.upper()
        charges.append(c)
    unconfirmed = [{"code": era.upper(), "raw": u.get("raw"), "section": u.get("section"),
                    "why": u.get("why"), "round": u.get("round")} for u in st.get("unconfirmed", [])]
    profile = st.get("facts_profile") or {}
    return {
        "status": result["status"],
        "era": era,
        "code_applied": ERA_NAME[era],
        "offence_date": st.get("offence_date"),
        "facts": st.get("case_facts"),
        "intake": result.get("intake"),
        "charges": charges,
        "unconfirmed": unconfirmed,
        "withdrawn": [{"code": era.upper(), "raw": w.get("raw"), "reason": w.get("reason")}
                      for w in st.get("withdrawn", [])],
        "included": [{**_charge(v), "code": era.upper(), "included_in": v["included_in"]}
                     for v in result.get("included", [])],
        "retries": st.get("retry_count", 0),
        "review_candidates": result.get("review_candidates", []),
        # The candidate list Node 1 read, in rank order, so a saved report can
        # replay the ledger's "retrieved" column instead of leaving it blank.
        "retrieved": [brief_row(r) for r in (st.get("retrieved") or [])[:RETRIEVED_KEPT]],
        # Real BGE-M3 vectors of the facts and of what retrieval found, in 2-D
        # (src/pipeline/embedmap.py). None for runs that did not compute it.
        "embedding_map": result.get("embedding_map"),
        "precedents": [{k: p.get(k) for k in ("label", "for_charge", "applies", "via_ipc_predecessor",
                                               "doc_id", "title", "court", "date", "citation",
                                               "disposal_nature", "similarity", "matched_by",
                                               "excerpt", "verified")}
                       for p in st.get("precedents", [])],
        "analytics": st.get("analytics") or {},
        "defenses": st.get("defenses", []),
        "facts_profile": {k: profile.get(k) for k in ("discloses_offence", "why", "accused_count")},
        "warnings": st.get("warnings", []),
        "guardrail": result.get("guardrail"),
        "timings": {k: round(v, 1) for k, v in result.get("timings", {}).items()},
    }
