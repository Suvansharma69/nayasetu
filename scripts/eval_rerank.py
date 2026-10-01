r"""Does a cross-encoder reranker improve statute retrieval? Scored on a fixture.

For each case: the pipeline's fused ranking (non-chargeable excluded, as Node 1
sees it) gives the top POOL candidates; bge-reranker-v2-m3 rescores them.
Reported, strict recall@k against the fixture's `relevant` sections:

    fused        the current pipeline ranking
    rerank       cross-encoder order alone
    rrf          reciprocal-rank fusion of the two (k=60, as in Phase 2)

Dev set by default (decisions allowed). Never run on a held-out set until the
method is frozen.

Run:  venv\Scripts\python.exe -u scripts\eval_rerank.py [--fixture F] [--pool 40]
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

from src.pipeline import applicability, chargeability  # noqa: E402
from src.retrieval import embedder, ranker, rerank, store  # noqa: E402

RRF_K = 60


def sec_of(cid):
    return cid.split("_s", 1)[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", default="tests/fixtures/phase2_testset.json")
    ap.add_argument("--pool", type=int, default=40)
    args = ap.parse_args()
    cases = json.loads((ROOT / args.fixture).read_text(encoding="utf-8"))["cases"]
    cli = store.client()

    pools = []
    for c in cases:        # all retrieval first, then free the embedder before the reranker loads
        era = c["era"]
        pools.append(ranker.rank_sections(c["query"], era, top_k=args.pool, cli=cli, device="cpu",
                                          exclude=chargeability.non_chargeable_sections(era)))
    embedder.free()

    ks = (1, 3, 5, 10)
    hits = {m: {k: 0 for k in ks} for m in ("fused", "rerank", "rrf")}
    rows, t0 = [], time.time()
    for c, pool in zip(cases, pools):
        era, want = c["era"], {sec_of(r) for r in c["relevant"]}

        def text_of(cand, era=era):
            sub = cand.get("matched") if cand.get("matched") not in (None, cand["section"]) else None
            return applicability.statute_text(era, cand["section"], sub)

        rr = rerank.rerank(c["query"], pool, text_of)
        fused_rank = {p["section"]: i + 1 for i, p in enumerate(pool)}
        rr_rank = {p["section"]: i + 1 for i, p in enumerate(rr)}
        rrf = sorted(fused_rank, key=lambda s: -(1 / (RRF_K + fused_rank[s]) + 1 / (RRF_K + rr_rank[s])))
        orders = {"fused": [p["section"] for p in pool], "rerank": [p["section"] for p in rr], "rrf": rrf}
        for m, order in orders.items():
            for k in ks:
                hits[m][k] += bool(want & set(order[:k]))
        rows.append({"query": c["query"][:80], "era": era, "want": sorted(want),
                     **{m: o[:5] for m, o in orders.items()}})
        print(f"[{era}] want={sorted(want)}  fused={orders['fused'][:3]}  rerank={orders['rerank'][:3]}  "
              f"rrf={orders['rrf'][:3]}", flush=True)
    rerank.free()
    n = len(cases)
    print(f"\n{args.fixture}  n={n}  pool={args.pool}  rerank time {time.time() - t0:.0f}s")
    for m in hits:
        print(f"  {m:<7} " + "  ".join(f"recall@{k} {hits[m][k]}/{n}" for k in ks))
    out = ROOT / "docs" / f"rerank_{Path(args.fixture).stem}_raw.json"
    out.write_text(json.dumps({"pool": args.pool, "hits": hits, "rows": rows}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
