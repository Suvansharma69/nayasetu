r"""Score the pipeline on IL-TUR LSI (see src/eval/lsi.py for exactly how).

    --split dev  --n 300    decisions may be made on these results
    --split test --n 1000   FROZEN: run once, after every decision is made

Resumable: each document's result is appended to docs/iltur_lsi_<split>_<n>.jsonl
as it finishes, and a re-run skips ids already there (except errors, which are
retried) -- a 1,000-document run
takes ~12 h on this machine. The summary (with a bootstrap 95% CI) is printed
and written to docs/iltur_lsi_<split>_<n>_summary.json.

Prerequisite: scripts/fetch_iltur.py (IL-TUR is gated; see that script).

Run:  venv\Scripts\python.exe -u scripts\eval_lsi.py --split dev --n 300 > lsi_dev.log 2>&1
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from src.eval import lsi  # noqa: E402
from src.graph import citation_graph as cg  # noqa: E402
from src.pipeline import chargeability, graph as pipeline, llm  # noqa: E402
from src.retrieval import embedder, store  # noqa: E402

PUBLISHED_BEST = {"LeSICiN": 28.08, "Hier. InLegalBERT": 26.23, "Hier. LegalBERT": 21.74}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed", type=int, default=20260927)
    ap.add_argument("--tag", default="", help="suffix for the output files, so a changed "
                    "pipeline is scored into its own file instead of resuming into the baseline's")
    args = ap.parse_args()
    stem = f"iltur_lsi_{args.split}_{args.n}" + (f"_{args.tag}" if args.tag else "")

    rows = lsi.sample(lsi.load(args.split), args.n, args.seed)
    labels = sorted(lsi.label_names().values())
    out = ROOT / "docs" / f"{stem}.jsonl"
    # an error (e.g. Ollama failing to start) is retried on a re-run; the new record
    # is appended and wins below, since `results` keeps the last record per id
    done = {r["id"] for r in lsi.read_results(out) if not r["status"].startswith("error")}
    print(f"model {llm.model()}  {args.split} sample {len(rows)} (seed {args.seed}); "
          f"{len(done)} already done", flush=True)

    g, cli = cg.load(), store.client()
    with out.open("a", encoding="utf-8") as fh:
        for i, r in enumerate(rows, 1):
            if r["id"] in done:
                continue
            t = time.perf_counter()
            try:
                res = pipeline.run(r["facts"], lsi.IPC_ERA_DATE, g=g, cli=cli)
                st = res["state"]
                pick = lambda xs, ks: [{k: x.get(k) for k in ks} for x in xs]  # noqa: E731
                rec = {"id": r["id"], "gold": r["labels"], "status": res["status"],
                       "verified": [v["section"] for v in st["verified_sections"]],
                       "charges": [v["section"] for v in res.get("charges", [])],
                       "retry_count": st["retry_count"],
                       "seconds": round(time.perf_counter() - t, 1),
                       # as in eval_phase6._record, so Phase 6's catch rate can be read off LSI too
                       "chars": len(r["facts"]),
                       "doubted": [d["section"] for d in res.get("doubted", [])],
                       "candidates": pick(st["candidate_sections"], ("raw", "section", "round")),
                       "unconfirmed": pick(st["unconfirmed"], ("raw", "section", "round", "why")),
                       "list": [x["section"] for x in st.get("retrieved", [])],
                       "intake": {k: (res.get("intake") or {}).get(k) for k in ("extracted", "why")}}
            except Exception as e:                  # recorded, never silently skipped
                rec = {"id": r["id"], "gold": r["labels"], "status": f"error: {e!r}"[:300],
                       "verified": [], "charges": [], "seconds": round(time.perf_counter() - t, 1)}
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(f"{i:4}/{len(rows)} {rec['status']:<14} gold={rec['gold']} charges={rec['charges']} "
                  f"{rec['seconds']}s", flush=True)
    embedder.free()

    results = {r["id"]: r for r in lsi.read_results(out)}
    recs = [results[r["id"]] for r in rows if r["id"] in results]
    gold = [set(r["gold"]) for r in recs]
    chargeable_labels = [l for l in labels
                         if chargeability.chargeable("ipc", lsi.base_section(l) or "")]
    summary = {"model": llm.model(), "split": args.split, "n": len(recs), "seed": args.seed,
               "tag": args.tag, "ablate": os.environ.get("PRAMANA_ABLATE", ""),
               "published_best_macro_f1": PUBLISHED_BEST,
               "errors": sum(r["status"].startswith("error") for r in recs)}
    for source in ("charges", "verified"):
        pred = [set(lsi.predicted_labels(r[source], labels)) for r in recs]
        m = lsi.metrics(gold, pred, labels)
        lo, hi = lsi.bootstrap_ci(gold, pred, labels)
        mc = lsi.metrics(gold, pred, chargeable_labels)
        summary[source] = {k: v for k, v in m.items() if k != "per_label_f1"}
        summary[source]["macro_f1_supported_ci95"] = [lo, hi]
        summary[source]["macro_f1_chargeable_labels"] = mc["macro_f1_supported"]
        summary[source]["per_label_f1"] = m["per_label_f1"]
        print(f"\n[{source}] macro-F1 {100 * m['macro_f1_supported']:.2f} "
              f"(95% CI {100 * lo:.2f}-{100 * hi:.2f}; {m['n_labels_supported']} labels with support)  "
              f"macro-F1 all-100 {100 * m['macro_f1_all']:.2f}  "
              f"micro P/R/F1 {100 * m['micro_precision']:.1f}/{100 * m['micro_recall']:.1f}/"
              f"{100 * m['micro_f1']:.1f}  chargeable-labels macro-F1 {100 * mc['macro_f1_supported']:.2f}")
    print(f"published best macro-F1: {PUBLISHED_BEST}")
    (ROOT / "docs" / f"{stem}_summary.json").write_text(
        json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
