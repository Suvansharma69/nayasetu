r"""Phase 1 build: raw sources -> data/processed/ -> validated.

Produces exactly the four corpora the Phase 2 ChromaDB collections are built
from (CLAUDE.md Section 5), as JSONL so a 2,500-judgment corpus streams rather
than sitting in memory twice:

    statutes_ipc.jsonl        ipc_sections
    statutes_bns.jsonl        bns_sections
    judgments_pre2024.jsonl   judgments_pre2024
    judgments_post2024.jsonl  judgments_post2024

The vanga SC judgments are split on DECISION DATE against 2024-07-01, the BNS
commencement the Stage 0 router keys on. The NyayaAnumana High Court subset has
no decision date to split on, so it is routed by the code each judgment applies
(see src/ingest/nyaya.py), into the same two files.

Nothing is written until it validates. Phase 1's gate is "processed JSON
validates against a fixed schema", so a chunk that fails is a build failure,
not a warning to scroll past.

Run:  venv\Scripts\python.exe scripts\build_corpus.py
      venv\Scripts\python.exe scripts\build_corpus.py --limit 20   (smoke)
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ingest import nyaya
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
        """Flush to the platform, then read the count back off disk.

        `self.n` is a number this process kept in memory; it proves nothing
        about the file. A build killed between the last write and the OS flush
        leaves a short file, and `build_report.json` -- which is written from
        these counters -- then states a total that no line of the corpus
        supports. That is not hypothetical: a killed rebuild once left
        `judgments_post2024.jsonl` at 0 lines while the report claimed 42,890.
        Reading the count back is the only version of this check that is worth
        anything, so it is done here rather than trusted.
        """
        self.fh.flush()
        os.fsync(self.fh.fileno())
        self.fh.close()
        on_disk = sum(1 for _ in self.path.open(encoding="utf-8"))
        if on_disk != self.n:
            raise SchemaError(
                f"{self.path.name}: {self.n} records written but {on_disk} lines "
                "on disk -- the write was truncated; this build is not usable"
            )


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


def build_judgments(index, report, pre, post, dup_index, limit=None):
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
                dup_index.add(c["doc_id"], c["text"])
            stats[f"judgments_{year}"] += 1
            if chunks[0]["sections_involved"]:
                stats["with_sections"] += 1
        print(
            f"  {year}: {docs} judgments in {time.time() - t0:.0f}s"
            f"  ({stats[f'judgments_{year}']} routed)"
        )

    report["judgment_stats"] = dict(stats)
    report["undated"] = undated
    print(f"  SC chunks: pre2024 {pre.n}, post2024 {post.n}")
    return stats


def build_nyaya(index, report, pre, post, dup_index, limit=None):
    """The filtered NyayaAnumana subset, appended to the same two files.

    Every rejected row is counted by the rule that rejected it, so the size of
    the subset is explained rather than just stated.
    """
    core_bns = nyaya.core_sections_bns()
    stats, families, courts, labels = Counter(), Counter(), Counter(), Counter()
    duplicates, seen_digests = [], set()
    pre0, post0 = pre.n, post.n
    t0 = time.time()

    for filename, text, label in nyaya.iter_rows():
        stats["rows_read"] += 1
        digest = nyaya.text_digest(text)
        if digest in seen_digests:
            stats["rejected_exact_duplicate"] += 1
            continue
        seen_digests.add(digest)

        route, sections, reason = nyaya.select(text, index, core_bns)
        if route is None:
            stats[f"rejected_{reason}"] += 1
            continue

        if filename.startswith("Supreme_Court_"):
            # Half the SC rows are judgments vanga already supplied; a second
            # copy would be counted twice by Node 5's outcome aggregation.
            doc, score = dup_index.match(nyaya.clean(text))
            if score >= nyaya.DuplicateIndex.THRESHOLD:
                stats["rejected_copy_of_vanga"] += 1
                duplicates.append([filename, doc, round(score, 3)])
                continue

        code = "ipc" if route == "pre" else "bns"
        chunks, hard = nyaya.chunk_row(filename, text, label, sections, code)
        if not chunks:
            stats["rejected_empty_after_cleaning"] += 1
            continue
        sink = pre if route == "pre" else post
        for c in chunks:
            sink.write(c)
        stats["kept"] += 1
        stats["hard_splits"] += hard
        courts[chunks[0]["court"]] += 1
        labels[label] += 1
        for fam, members in nyaya.OFFENCE_FAMILIES.items():
            if set(sections) & members:
                families[fam] += 1
        if "34" in sections:
            families["with_common_intention_s34"] += 1
        if limit and stats["kept"] >= limit:
            break

    report["nyaya"] = {
        "stats": dict(stats),
        "chunks_pre2024": pre.n - pre0,
        "chunks_post2024": post.n - post0,
        "offence_families": dict(families),
        "courts": dict(courts.most_common()),
        "outcome_labels": {str(k): v for k, v in labels.items()},
        "copies_of_vanga": duplicates,
    }
    print(f"  NyayaAnumana: {stats['rows_read']} rows read, {stats['kept']} kept "
          f"in {time.time() - t0:.0f}s -> {pre.n - pre0} pre2024 / "
          f"{post.n - post0} post2024 chunks")
    for k, v in sorted(stats.items()):
        if k.startswith("rejected_"):
            print(f"    {k:34} {v}")
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
    pre = Writer(OUT / "judgments_pre2024.jsonl")
    post = Writer(OUT / "judgments_post2024.jsonl")
    dup_index = nyaya.DuplicateIndex()
    build_judgments(index, report, pre, post, dup_index, limit=args.limit)
    build_nyaya(index, report, pre, post, dup_index, limit=args.limit)
    pre.close()
    post.close()
    report["judgments_pre2024"] = pre.n
    report["judgments_post2024"] = post.n
    print(f"  judgments_pre2024.jsonl   {pre.n} chunks")
    print(f"  judgments_post2024.jsonl  {post.n} chunks")

    (OUT / "build_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nreport -> {OUT / 'build_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
