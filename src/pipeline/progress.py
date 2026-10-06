r"""Stage events for a running analysis, for the web interface's live view.

Each event is {"stage", "phase": "start" | "done", "data"}: `start` when a stage
begins, `done` with a small JSON-safe summary of what it produced (the sections
proposed, verified, rejected, judged...). The page animates exactly these, so
what it shows is what the pipeline did -- nothing is simulated.

`mark()` is a no-op unless a listener is installed with `listening(fn)`. The
API runs one analysis at a time (the GPU handoff, src/api/main.py), so a single
module-level listener is enough. Nodes 3 and 5 run in parallel; both report.
"""
from __future__ import annotations

from contextlib import contextmanager

STAGES = {
    "intake": "Checking whether this is a court order or FIR",
    "route": "Choosing the code from the offence date",
    "retrieve": "Searching statutes and judgments",
    "statute_identifier": "Proposing sections (local model)",
    "verifier": "Verifying every citation against the citation graph",
    "applicability": "Checking each section against the facts",
    "precedents": "Matching precedent judgments",
    "analytics": "Aggregating outcomes",
    "defense": "Drafting counter-arguments",
}

_listener = None


def mark(stage, phase="start", data=None):
    if _listener is not None:
        _listener({"stage": stage, "phase": phase, "data": data})


@contextmanager
def listening(fn):
    global _listener
    prev, _listener = _listener, fn
    try:
        yield
    finally:
        _listener = prev


def _ref(v):
    return v.get("subsection") or v.get("section")


def summarise(stage, update):
    """What a graph node produced, small enough to stream to the page."""
    u = update or {}
    if stage == "statute_identifier":
        rnd = u.get("retry_count", 0)
        prof = u.get("facts_profile") or {}
        return {"round": rnd,
                "proposals": [{"raw": c["raw"], "source": c.get("source")}
                              for c in u.get("candidate_sections", []) if c.get("round") == rnd],
                "withdrawn": [w["raw"] for w in u.get("withdrawn", []) if w.get("round") == rnd],
                "profile": {k: prof.get(k) for k in ("discloses_offence", "accused_count", "injury",
                                                    "dangerous_weapon")} if prof else None}
    if stage == "verifier":
        return {"verified": [{"ref": _ref(v), "section": v["section"], "title": v.get("title"),
                              "raw": v.get("raw"), "defined_in": v.get("defined_in")}
                             for v in u.get("verified_sections", [])],
                "unconfirmed": [{"raw": x.get("raw"), "why": x.get("why"), "round": x.get("round")}
                                for x in u.get("unconfirmed", [])]}
    if stage == "applicability":
        return {"checks": [{"ref": _ref(a), "section": a["section"], "supported": a.get("supported"),
                            "included_in": a.get("included_in"),
                            "rule": a.get("rule_rejected") or a.get("supported_by_rule")}
                           for a in u.get("applicability", [])]}
    if stage == "precedents":
        by = {}
        for p in u.get("precedents", []):
            by[p["for_charge"]] = by.get(p["for_charge"], 0) + 1
        return {"count": len(u.get("precedents", [])), "by_charge": by}
    if stage == "analytics":
        a = u.get("analytics") or {}
        return {"sections": [s["charge"] for s in a.get("sections", [])]}
    if stage == "defense":
        d = u.get("defenses", [])
        return {"count": len(d), "verified": sum(1 for x in d if x.get("verified"))}
    return None


def staged(name, fn):
    """Wrap a graph node so it reports when it starts and what it produced."""
    def node(state):
        mark(name)
        out = fn(state)
        try:
            data = summarise(name, out)
        except Exception:  # noqa: BLE001 -- a summary must never break an analysis
            data = None
        mark(name, "done", data)
        return out
    node.__name__ = name
    return node
