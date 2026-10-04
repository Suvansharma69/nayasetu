r"""Node 5's offline batch job: the outcomes table, in SQLite.

One row per ingested judgment (court, year, how it was disposed of) and one row
per case -> section edge, taken from the citation graph -- so a judgment counts
for a section only through the same audited edges Node 3 uses (96% precision on
the 2026-09-27 audit), never through a fresh extraction.

What `disposal` means, measured (CLAUDE.md Known Gotchas, 2026-09-26): it is how
THAT court disposed of the appeal or petition -- "allowed" means the appellant
or petitioner won. It is NOT a conviction rate: an allowed appeal can be an
acquittal or a State appeal restoring a conviction. Sentence ranges are not
extracted (judgments mostly quote the trial court's sentence; see gotchas).

Run:  venv\Scripts\python.exe scripts\build_outcomes.py      (seconds; rebuild after build_graph.py)
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.graph import citation_graph as cg  # noqa: E402
from src.pipeline.analytics import DB_PATH, bucket  # noqa: E402


def main():
    g = cg.load()
    DB_PATH.unlink(missing_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE cases (doc_id TEXT PRIMARY KEY, court TEXT, source TEXT, year INTEGER,
                            disposal_raw TEXT, disposal TEXT, title TEXT);
        CREATE TABLE cites (doc_id TEXT, code TEXT, section TEXT, PRIMARY KEY (doc_id, code, section));
    """)
    n_cases = n_cites = 0
    for n, d in g.nodes(data=True):
        if d.get("kind") != "case":
            continue
        date = d.get("date") or ""
        year = int(date[:4]) if date[:4].isdigit() else d.get("decision_year_min")
        con.execute("INSERT INTO cases VALUES (?,?,?,?,?,?,?)",
                    (d["doc_id"], d.get("court"), d.get("source"), year,
                     d.get("disposal_nature"), bucket(d.get("disposal_nature")), d.get("title")))
        n_cases += 1
        for s in g.successors(n):
            e = g.edges[n, s]
            if e.get("kind") == "cites":
                sd = g.nodes[s]
                con.execute("INSERT OR IGNORE INTO cites VALUES (?,?,?)", (d["doc_id"], sd["code"], sd["section"]))
                n_cites += 1
    con.execute("CREATE INDEX cites_by_section ON cites (code, section)")
    con.commit()
    for row in con.execute("SELECT disposal, COUNT(*) FROM cases GROUP BY disposal ORDER BY 2 DESC"):
        print(f"  {row[0]:15} {row[1]}")
    con.close()
    print(f"{n_cases} judgments, {n_cites} case->section rows -> {DB_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
