r"""Phase 2 gate: section retrieval on the 15 hand-written cases, via the REAL index.

Unlike embedding_bakeoff.py (which embeds in memory to compare models), this
queries the ChromaDB collections that the pipeline will use, through the same
functions the pipeline will call. Two methods are scored side by side:

    statute   store.retrieve_sections   (statute collection only)
    fused     ranker.rank_sections      (statute + precedent votes, RRF)

CLAUDE.md Section 8's gate is "top-3 results manually judged relevant in at
least 12/15" -- a human judgement. The recall@3 printed here is the strict
automatic proxy against the fixture's `relevant` lists; the per-case top-3 is
printed so it can be read and judged, and the judgement is recorded in
docs/phase2_retrieval.md.

Run:  venv\Scripts\python.exe scripts\eval_retrieval.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from src.pipeline import chargeability, hyde, llm  # noqa: E402
from src.retrieval import embedder, ranker, store  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "phase2_testset.json"
HELDOUT = ROOT / "tests" / "fixtures" / "phase2_heldout.json"


def section_of(chunk_id):
    # "ipc_s378" -> "378", "bns_s3" -> "3"
    return chunk_id.split("_s", 1)[1]


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", action="store_true",
                    help="score the ranking the PIPELINE uses: non-chargeable sections "
                         "(definitions, general exceptions) excluded and IPC definition/punishment "
                         "ranks pooled, as graph.retrieve_candidates does")
    ap.add_argument("--hyde", action="store_true",
                    help="with --pipeline: search statutes with the LLM's abstract restatement "
                         "of the facts (src/pipeline/hyde.py); needs Ollama")
    ap.add_argument("--heldout", action="store_true",
                    help="score tests/fixtures/phase2_heldout.json instead (never tune on it)")
    args = ap.parse_args()
    fixture = HELDOUT if args.heldout else FIXTURE
    cases = json.loads(fixture.read_text(encoding="utf-8"))["cases"]
    cli = store.client()
    rows, hits = [], {"statute": 0, "fused": 0}
    for i, case in enumerate(cases, 1):
        era = case["era"]
        want = {section_of(r) for r in case["relevant"]}
        statute = store.retrieve_sections(case["query"], ranker.ERA[era]["statutes"],
                                          top_k=3, cli=cli)
        sq = hyde.restate(case["query"], llm.chat_json) if args.hyde else None
        fused = ranker.rank_sections(case["query"], era, top_k=3, cli=cli, statute_query=sq,
                                     exclude=chargeability.non_chargeable_sections(era) if args.pipeline else None,
                                     pairs=chargeability.pairs(era) if args.pipeline else None)
        if sq:
            print(f"    hyde: {sq[:160]}")
        for name, res in (("statute", statute), ("fused", fused)):
            if want & {r["section"] for r in res}:
                hits[name] += 1
        rows.append((i, case, want, statute, fused))
        print(f"\n{i:2}. [{era}] {case.get('offence_type')}  want={sorted(want, key=str)}")
        print(f"    {case['query'][:150]}")
        for name, res in (("statute", statute), ("fused  ", fused)):
            mark = "HIT " if want & {r["section"] for r in res} else "miss"
            shown = "; ".join(f"s{r['section']}"
                              + (f" [{r['matched']}]" if r.get("matched") not in (None, r["section"]) else "")
                              + f" {(r.get('title') or '')[:38]}" for r in res)
            print(f"    {name} {mark}: {shown}")

    n = len(cases)
    print(f"\nrecall@3 (strict, vs fixture):  statute {hits['statute']}/{n}   "
          f"fused {hits['fused']}/{n}   "
          + ("(held out: a check, not the gate)" if args.heldout
             else "(gate: 12/15 top-3 relevant, judged manually)"))
    embedder.free()
    out = ROOT / "docs" / (("phase2_retrieval_heldout" if args.heldout else "phase2_retrieval")
                           + ("_pipeline" if args.pipeline else "") + ("_hyde" if args.hyde else "")
                           + "_raw.json")
    out.write_text(json.dumps([
        {"case": i, "era": c["era"], "offence_type": c.get("offence_type"),
         "query": c["query"], "want": sorted(w),
         "statute_top3": [(r["section"], r.get("matched"), r.get("title")) for r in s],
         "fused_top3": [(r["section"], r.get("matched"), r.get("title"),
                         r.get("statute_rank"), r.get("vote_rank")) for r in f]}
        for i, c, w, s, f in rows], indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"raw -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
