r"""Score the pipeline on a case fixture: routing, recall and over-charging.

    --fixture tests/fixtures/broad_coverage.json   (default; HELD OUT -- run once per
                                                    method change, never tune on it)
    --fixture tests/fixtures/phase2_testset.json   (the dev set: allowed for decisions)

For every case it compares the expected sections (`relevant`; `arguable` ones are
not counted against the pipeline) with two outputs:

    verified   every section Node 2 verified (existence only -- Phase 4's output)
    charges    verified AND supported by Node 2b's grounded applicability check

Reported: routing; recall (a relevant section present); extras (sections outside
relevant + arguable, i.e. over-charging); relevant sections Node 2b rejected
(the recall cost of the check); grounded-quote rate.

Run:  venv\Scripts\python.exe -u scripts\eval_broad.py [--fixture F] [--out NAME] > log 2>&1
"""
import argparse
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


def _sec(cid):
    return cid.split("_s", 1)[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", default="tests/fixtures/broad_coverage.json")
    ap.add_argument("--out", default=None, help="docs/<out>_raw.json (default: from fixture name)")
    ap.add_argument("--no-applicability", action="store_true", help="Phase 4 behaviour, for comparison")
    args = ap.parse_args()
    fixture = ROOT / args.fixture
    out_name = args.out or fixture.stem
    g, cli = cg.load(), store.client()
    cases = json.loads(fixture.read_text(encoding="utf-8"))["cases"]
    rows = []
    tot = {"n": 0, "routed": 0, "rec_verified": 0, "rec_charges": 0, "extra_verified": 0,
           "extra_charges": 0, "relevant_rejected_by_2b": 0, "quotes": 0, "quotes_grounded": 0}
    for i, c in enumerate(cases, 1):
        cid = c.get("id", i)
        out = pipeline.run(c["query"], c["offence_date"], g=g, cli=cli,
                           check_applicability=not args.no_applicability)
        st = out["state"]
        rel = {_sec(x) for x in c["relevant"]}
        ok_set = rel | {_sec(x) for x in c.get("arguable", [])}
        ver = {v["section"] for v in st["verified_sections"]}
        chg = {v["section"] for v in out["charges"]}
        gated = c.get("gated", True)
        r = {"id": cid, "era": c["era"], "offence_type": c.get("offence_type"), "status": out["status"],
             "routed_ok": out["era"] == c["era"], "want": sorted(rel),
             "verified": sorted(ver), "charges": sorted(chg), "unsupported": sorted(ver - chg),
             "extra_verified": sorted(ver - ok_set), "extra_charges": sorted(chg - ok_set),
             "relevant_rejected_by_2b": sorted((ver & rel) - chg),
             "facts_profile": st.get("facts_profile"), "applicability": st.get("applicability"),
             "unconfirmed": [u["raw"] for u in st["unconfirmed"]],
             "timings": {k: round(v, 1) for k, v in out["timings"].items()}, "gated": gated}
        rows.append(r)
        if gated:
            tot["n"] += 1
            tot["routed"] += r["routed_ok"]
            tot["rec_verified"] += bool(ver & rel)
            tot["rec_charges"] += bool(chg & rel)
            tot["extra_verified"] += len(r["extra_verified"])
            tot["extra_charges"] += len(r["extra_charges"])
            tot["relevant_rejected_by_2b"] += len(r["relevant_rejected_by_2b"])
            for a in st.get("applicability") or []:
                tot["quotes"] += len(a["grounded_quotes"]) + len(a["dropped_quotes"])
                tot["quotes_grounded"] += len(a["grounded_quotes"])
        print(f"#{cid:>2} [{c['era']}] {str(c.get('offence_type'))[:30]:<30} {out['status']:<20} "
              f"want={sorted(rel)} charges={sorted(chg)} unsupported={r['unsupported']} "
              f"extra={r['extra_charges']} lost={r['relevant_rejected_by_2b']} "
              f"{out['timings'].get('graph_s', 0):.0f}s", flush=True)
    embedder.free()
    n = tot["n"]
    print(f"\nmodel {llm.model()}  {fixture.name}  gated {n}: routed {tot['routed']}/{n}")
    print(f"  recall  verified {tot['rec_verified']}/{n}   charges {tot['rec_charges']}/{n}")
    print(f"  extras  verified {tot['extra_verified']}   charges {tot['extra_charges']}   "
          f"relevant sections rejected by 2b: {tot['relevant_rejected_by_2b']}")
    print(f"  quotes grounded {tot['quotes_grounded']}/{tot['quotes']}")
    (ROOT / "docs" / f"{out_name}_raw.json").write_text(
        json.dumps({"model": llm.model(), "fixture": args.fixture, "totals": tot, "cases": rows},
                   indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
