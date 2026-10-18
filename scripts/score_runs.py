r"""Re-score saved pipeline runs (stuff/docs/<name>_runs.jsonl) against a fixture, the same way for all.

eval_broad.py scores a run as it happens; this re-scores any saved run under one
rule set, so a baseline and a new method are compared like for like:

* Offence identity: an IPC definition and the section that punishes it are the
  same charge (378 theft / 379 punishment for theft). The fixtures often list
  the definition, while a charge is framed under the punishing section -- so both
  the answer key and the output are mapped definition -> punishment before
  comparing. Pairs come from data/mappings/chargeability.json (`punished_by`).
* recall    = cases with at least one relevant section charged
* precision = charged sections that are relevant or arguable / all charged
* false decline = no relevant section charged AND none in the review list, and
  either the run was refused (insufficient data) or nothing was charged.
* "set aside" = precision if the sections the advisory judge doubted are left out.

Run:  venv\Scripts\python.exe scripts\score_runs.py tests\fixtures\phase2_testset.json stuff\docs\single_dev_runs.jsonl [more runs...]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUN = json.loads((ROOT / "data" / "mappings" / "chargeability.json").read_text(encoding="utf-8"))["punished_by"]


def canon(era, s):
    return PUN.get(era, {}).get(s, s)


def key(cid):
    era, s = cid.split("_s", 1)
    return canon(era, s)


def score(fixture, runs_path):
    cases = {c.get("id", i): c for i, c in enumerate(
        json.loads(Path(fixture).read_text(encoding="utf-8"))["cases"], 1)}
    runs = [json.loads(l) for l in Path(runs_path).read_text(encoding="utf-8").splitlines() if l.strip()]
    n = rec = chg_n = good = kept_n = kept_good = declines = 0
    misses = []
    for r in runs:
        c = cases[r["id"]]
        if not c.get("gated", True):
            continue
        era = r["era"]
        rel = {key(x) for x in c["relevant"]}
        ok = rel | {key(x) for x in c.get("arguable", [])}
        chg = {canon(era, s) for s in r["charges"]}
        doubted = {canon(era, d["section"]) for d in r.get("doubted", [])}
        review = {canon(era, s) for s in r.get("review", [])}
        n += 1
        hit = bool(chg & rel)
        rec += hit
        chg_n += len(chg)
        good += len(chg & ok)
        kept = chg - doubted
        kept_n += len(kept)
        kept_good += len(kept & ok)
        if not hit and not (review & rel) and (r["status"] == "insufficient_data" or not chg):
            declines += 1
        if not hit:
            misses.append(f"#{r['id']} want {sorted(rel)} got {sorted(chg)}")
    pct = lambda a, b: f"{a}/{b} = {100 * a / b:.0f}%" if b else "-"  # noqa: E731
    print(f"{Path(runs_path).name}: n={n}  recall {rec}/{n}  precision {pct(good, chg_n)}  "
          f"doubted set aside {pct(kept_good, kept_n)}  sections/case {chg_n / max(n, 1):.1f}  "
          f"false declines {declines}")
    for m in misses:
        print("   miss", m)


if __name__ == "__main__":
    for p in sys.argv[2:]:
        score(sys.argv[1], p)
