r"""Phase 1 build: raw sources -> data/processed/ -> validated.

Produces exactly the four corpora the Phase 2 ChromaDB collections are built
from (CLAUDE.md Section 5), as JSONL so a 2,500-judgment corpus streams rather
than sitting in memory twice:

    statutes_ipc.jsonl        ipc_sections
    statutes_bns.jsonl        bns_sections
    judgments_pre2024.jsonl   judgments_pre2024
    judgments_post2024.jsonl  judgments_post2024

The judgment split is on DECISION DATE against 2024-07-01, the BNS
commencement the Stage 0 router keys on.

Nothing is written until it validates. Phase 1's gate is "processed JSON
validates against a fixed schema", so a chunk that fails is a build failure,
not a warning to scroll past.

Run:  venv\Scripts\python.exe scripts\build_corpus.py
      venv\Scripts\python.exe scripts\build_corpus.py --limit 20   (smoke)
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ingest.judgments import BNS_COMMENCEMENT, iter_judgments, load_metadata
from src.ingest.schema import SchemaError, validate_chunk
from src.ingest.sections import section_index
from src.ingest.statutes import parse_bns, parse_ipc

OUT = ROOT / "data" / "processed"
YEARS = (2023, 2024, 2025)


class Writer:
    """JSONL sink that validates every record on the way past."""

    def __init__(self, path):
        self.path = path
        self.fh = path.open("w", encoding="utf-8")
        self.n = 0
        self.seen = set()

    def write(self, chunk):
        validate_chunk(chunk)
        if chunk["chunk_id"] in self.seen:
            raise SchemaError(f"duplicate chunk_id {chunk['chunk_id']}")
        self.seen.add(chunk["chunk_id"])
        self.fh.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        self.n += 1

    def close(self):
        self.fh.close()


def build_statutes(report):
    OUT.mkdir(parents=True, exist_ok=True)

    ipc, skipped = parse_ipc()
    bns = parse_bns()

    for name, chunks in (("ipc", ipc), ("bns", bns)):
        w = Writer(OUT / f"statutes_{name}.jsonl")
        for c in chunks:
            w.write(c)
        w.close()
        report[f"statutes_{name}"] = w.n
        print(f"  statutes_{name}.jsonl  {w.n} sections")

    report["ipc_skipped"] = skipped
    report["bns_missing_titles"] = [c["section"] for c in bns if not c["section_title"]]
    if skipped:
        # Loud, because a silently absent section is one the verifier will
        # later reject as fabricated when a judgment legitimately cites it.
        print(f"  [gap] IPC sections omitted (no upstream text): {skipped}")
        print("        tracked in data/mappings/statute_patches.json")
    return ipc, bns


def build_judgments(index, report, limit=None):
    pre = Writer(OUT / "judgments_pre2024.jsonl")
    post = Writer(OUT / "judgments_post2024.jsonl")
    stats = Counter()
    undated = []

    for year in YEARS:
        meta = load_metadata(year)
        t0, docs = time.time(), 0
        for key, chunks in iter_judgments(year, meta, index, limit=limit):
            docs += 1
            if not chunks:
                stats["empty_judgments"] += 1
                continue
            date = chunks[0]["date"]
            if date is None:
                # Cannot be routed to a side of the BNS transition, so it is
                # not silently dropped into one; it is reported instead.
                undated.append(key)
                stats["undated"] += 1
                continue
            sink = post if date >= BNS_COMMENCEMENT else pre
            for c in chunks:
                sink.write(c)
            stats[f"judgments_{year}"] += 1
            if chunks[0]["sections_involved"]:
                stats["with_sections"] += 1
        print(
            f"  {year}: {docs} judgments in {time.time() - t0:.0f}s"
            f"  ({stats[f'judgments_{year}']} routed)"
        )

    pre.close()
    post.close()
    report["judgments_pre2024"] = pre.n
    report["judgments_post2024"] = post.n
    report["judgment_stats"] = dict(stats)
    report["undated"] = undated
    print(f"  judgments_pre2024.jsonl   {pre.n} chunks")
    print(f"  judgments_post2024.jsonl  {post.n} chunks")
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="judgments per year, for smoke runs")
    args = ap.parse_args()

    report = {}
    print("statutes:")
    ipc, bns = build_statutes(report)
    index = section_index(ipc, bns)
    report["verification_sets"] = {k: len(v) for k, v in index.items()}
    print(f"  verification sets: ipc={len(index['ipc'])} bns={len(index['bns'])}"
          f" union={len(index['_union'])}\n")

    print("judgments:")
    build_judgments(index, report, limit=args.limit)

    (OUT / "build_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nreport -> {OUT / 'build_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
