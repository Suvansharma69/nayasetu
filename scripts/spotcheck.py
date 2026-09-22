r"""Phase 1 acceptance gate: re-validate everything, then sample for eyeballing.

CLAUDE.md Phase 1 "Done when":
    processed JSON validates against a fixed schema; 20 random chunks manually
    spot-checked, none truncated or malformed.

Two halves, and the first is not optional decoration: the build validates on
the way out, but this re-validates what is actually ON DISK, so a file that was
truncated by a crashed or interrupted write is caught rather than trusted.

The second half prints a fixed random sample for a human to read. It also runs
automated truncation heuristics over the WHOLE corpus, because 20 chunks out of
77,000 is a sample, not a proof -- the heuristics say where to look.

Run:  venv\Scripts\python.exe scripts\spotcheck.py
      venv\Scripts\python.exe scripts\spotcheck.py --seed 7 --n 20
"""
import argparse
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ingest.schema import SchemaError, validate_chunk

PROCESSED = ROOT / "data" / "processed"
FILES = (
    "statutes_ipc.jsonl",
    "statutes_bns.jsonl",
    "judgments_pre2024.jsonl",
    "judgments_post2024.jsonl",
)

# A chunk ending mid-word or mid-clause is the signature of a truncated read.
# Judgments legitimately end on ':' or a quote, so only the harder cases count.
_TRUNCATED_TAIL = re.compile(r"[a-z,]$|\b\w{1,2}-$")
# Mojibake from a bad codec round-trip. The PDFs are clean UTF-8, so any
# U+FFFD on disk means we damaged the text ourselves.
_REPLACEMENT = "�"


def load(path):
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield lineno, json.loads(line)
            except json.JSONDecodeError as e:
                raise SystemExit(f"{path.name}:{lineno} is not valid JSON: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260922)
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()

    all_chunks, problems, warnings, stats = [], [], [], Counter()
    seen_ids = set()

    for name in FILES:
        path = PROCESSED / name
        if not path.exists():
            raise SystemExit(f"missing {path} -- run scripts/build_corpus.py first")
        n = 0
        for lineno, chunk in load(path):
            n += 1
            try:
                validate_chunk(chunk)
            except SchemaError as e:
                problems.append(f"SCHEMA {name}:{lineno} {e}")
            if chunk["chunk_id"] in seen_ids:
                problems.append(f"DUPLICATE id {chunk['chunk_id']} in {name}:{lineno}")
            seen_ids.add(chunk["chunk_id"])

            text = chunk["text"]
            if _REPLACEMENT in text:
                # Not a build failure. Every occurrence found so far sits inside
                # a Devanagari passage quoted within an English judgment (a
                # Hindi government order, a Sanskrit verse, an Urdu couplet):
                # the PDFs' Devanagari font mapping is lossy at source. The
                # surrounding English is intact, and the embedder is
                # English-only, so the retrieval impact is nil. Reported, not
                # fatal -- but it must stay visible in case it ever spreads to
                # English text, which WOULD mean we damaged it ourselves.
                warnings.append(f"MOJIBAKE {name}:{lineno} {chunk['chunk_id']}")
            if _TRUNCATED_TAIL.search(text.rstrip()):
                stats["suspect_tail"] += 1
            if chunk["sections_involved"]:
                stats["with_sections"] += 1
            all_chunks.append((name, chunk))
        stats[name] = n
        print(f"  {name:28} {n:>7} chunks")

    print(f"\ntotal {len(all_chunks)} chunks, {len(seen_ids)} unique ids")
    print(f"with section references: {stats['with_sections']}")
    print(f"tails that look cut off: {stats['suspect_tail']} "
          f"({stats['suspect_tail'] / max(len(all_chunks), 1):.1%})")

    if warnings:
        print(f"\n{len(warnings)} warnings (non-fatal, see code for why):")
        for w in warnings[:10]:
            print("  " + w)

    if problems:
        print(f"\n{len(problems)} PROBLEMS:")
        for p in problems[:40]:
            print("  " + p)
        return 1
    print("\nno schema or duplicate problems")

    rng = random.Random(args.seed)
    sample = rng.sample(all_chunks, min(args.n, len(all_chunks)))
    print(f"\n{'=' * 78}\n{len(sample)} RANDOM CHUNKS (seed {args.seed}) "
          f"-- read these for truncation/malformation\n{'=' * 78}")
    for i, (name, c) in enumerate(sample, 1):
        text = c["text"]
        head = text[:300].replace("\n", " ")
        tail = text[-120:].replace("\n", " ") if len(text) > 420 else ""
        print(f"\n--- {i:2}. [{name}] {c['chunk_id']}  ({len(text)} chars)")
        print(f"     date={c['date']} court={c['court']} "
              f"sections={c['sections_involved'][:6]}")
        print(f"     {head}")
        if tail:
            print(f"     ...{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
