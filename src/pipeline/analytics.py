r"""Node 5: outcome analytics. Pure SQL over the pre-built outcomes table -- no
LLM call, no embedding (CLAUDE.md Section 3). Reads only verified_sections.

Built offline by scripts/build_outcomes.py. A section supported by fewer than
MIN_JUDGMENTS judgments is suppressed: a percentage over three cases is noise
presented as a statistic. For a BNS section, the IPC predecessor's figures
are shown as well (and labelled as such), because almost no BNS case has
reached a reported appeal yet.

The figures are APPEAL/PETITION OUTCOMES at the court that decided them, not
conviction rates -- see scripts/build_outcomes.py.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "outcomes.sqlite"
MIN_JUDGMENTS = 5
BUCKETS = ("allowed", "partly allowed", "dismissed", "other")
NOTE = ("How the appeal or petition was disposed of by the court that decided it "
        "(allowed = the appellant/petitioner succeeded). Not a conviction rate.")

_ALLOWED = {"allowed", "appeal(s) allowed", "case allowed"}


def bucket(raw):
    r = (raw or "").strip().lower()
    if r in _ALLOWED:
        return "allowed"
    if r == "case partly allowed":
        return "partly allowed"
    if r == "dismissed":
        return "dismissed"
    return "other"


def section_stats(con, code, section):
    rows = con.execute(
        "SELECT c.disposal, COUNT(*) FROM cites s JOIN cases c ON c.doc_id = s.doc_id "
        "WHERE s.code = ? AND s.section = ? GROUP BY c.disposal", (code, section)).fetchall()
    counts = {b: 0 for b in BUCKETS}
    counts.update(dict(rows))
    n = sum(counts.values())
    decided = n - counts["other"]
    out = {"code": code, "section": section, "judgments": n, "counts": counts,
           "suppressed": n < MIN_JUDGMENTS}
    if not out["suppressed"] and decided:
        out["allowed_share"] = round((counts["allowed"] + counts["partly allowed"]) / decided, 3)
    return out


def outcome_analytics(state, g=None, db_path=None):
    """Node 5. {"analytics": {"note", "min_judgments", "sections": [...]}}."""
    from src.graph import citation_graph as cg

    from .applicability import charged

    db = Path(db_path or DB_PATH)
    if not db.exists():
        return {"analytics": {"error": f"outcomes table missing: run scripts/build_outcomes.py ({db.name})"}}
    era = state["era"]
    con = sqlite3.connect(db)
    try:
        sections, seen = [], set()
        for v in charged(state):  # verified, less sections included in a greater charge
            if v["section"] in seen:
                continue
            seen.add(v["section"])
            entry = {"charge": f"{era.upper()} {v['section']}", "title": v.get("title"),
                     "direct": section_stats(con, era, v["section"]), "via_ipc": []}
            if era == "bns" and g is not None:
                entry["via_ipc"] = [section_stats(con, "ipc", p)
                                    for p in cg.get_ipc_predecessors(g, v["section"])]
            sections.append(entry)
    finally:
        con.close()
    return {"analytics": {"note": NOTE, "min_judgments": MIN_JUDGMENTS, "sections": sections}}
