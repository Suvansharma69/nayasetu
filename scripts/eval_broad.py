r"""Score the pipeline (router -> retrieval -> guardrail -> Node 1 <-> Node 2) on
tests/fixtures/broad_coverage.json. HELD OUT: run once per method change, never tune on it.

Per case it reports whether the router picked the case's era, what was verified,
and whether a `relevant` section (or, separately, an `arguable` one) was verified.
Writes docs/broad_coverage_raw.json.

Run:  venv\Scripts\python.exe -u scripts\eval_broad.py > broad.log 2>&1
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from src.graph import citation_graph as cg  # noqa: E402
from src.pipeline import graph as pipeline, llm  # noqa: E402
from src.retrieval import embedder, store  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "broad_coverage.json"


def _sec(cid):
    return cid.split("_s", 1)[1]


def main():
    g, cli = cg.load(), store.client()
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    rows, n_route, n_rel, n_any, n_gated = [], 0, 0, 0, 0
    for c in cases:
        out = pipeline.run(c["query"], c["offence_date"], g=g, cli=cli)
        st = out["state"]
        got = {v["section"] for v in st["verified_sections"]}
        rel, arg = {_sec(x) for x in c["relevant"]}, {_sec(x) for x in c.get("arguable", [])}
        routed = out["era"] == c["era"]
        hit_rel, hit_any = bool(got & rel), bool(got & (rel | arg))
        gated = c.get("gated", True)
        if gated:
            n_gated += 1
            n_route += routed
            n_rel += hit_rel
            n_any += hit_any
        extra = sorted(got - rel - arg, key=lambda s: (len(s), s))
        rows.append({"id": c["id"], "era": c["era"], "offence_type": c["offence_type"], "status": out["status"],
                     "routed_ok": routed, "relevant_verified": hit_rel, "relevant_or_arguable": hit_any,
                     "verified": [v["subsection"] or v["section"] for v in st["verified_sections"]],
                     "verified_titles": {v["section"]: v.get("title") for v in st["verified_sections"]},
                     "outside_expected": extra, "want": sorted(rel), "arguable": sorted(arg),
                     "unconfirmed": [u["raw"] for u in st["unconfirmed"]], "retry_count": st["retry_count"],
                     "guardrail": out.get("guardrail"),
                     "timings": {k: round(v, 1) for k, v in out["timings"].items()}, "gated": gated})
        print(f"#{c['id']:2} [{c['era']}] {c['offence_type'][:34]:<34} {'route-ok' if routed else 'ROUTE-FAIL'} "
              f"{'HIT ' if hit_rel else ('arg ' if hit_any else 'MISS')} verified={rows[-1]['verified']} "
              f"want={sorted(rel)} extra={extra} unconf={rows[-1]['unconfirmed']}", flush=True)
    embedder.free()
    print(f"\nmodel {llm.model()}  gated cases {n_gated}: routed {n_route}/{n_gated}, relevant verified "
          f"{n_rel}/{n_gated}, relevant-or-arguable {n_any}/{n_gated}")
    (ROOT / "docs" / "broad_coverage_raw.json").write_text(
        json.dumps({"model": llm.model(), "cases": rows}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
