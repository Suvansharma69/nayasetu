r"""Phase 2: embed data/processed/ into the four ChromaDB collections.

Each collection is dropped and rebuilt whole (see store.build for why), and the
stored count is checked against the corpus file before this reports success.

Run:  venv\Scripts\python.exe scripts\build_index.py
      venv\Scripts\python.exe scripts\build_index.py --only ipc_sections bns_sections

Set HF_HUB_OFFLINE=1 once the model is cached: on this link a hub metadata
check can stall a load for many minutes (it did, 2026-09-26).
"""
import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from src.retrieval import embedder, store  # noqa: E402

# Statutes are few but long (BNS s3 runs to ~1,500 tokens) and BGE-M3 attends
# over its full 8,192-token window, so they go in small batches to stay inside
# 4GB of VRAM. Judgment chunks are ~1,200 chars and batch comfortably.
ENCODE_BATCH = {"ipc_sections": 4, "bns_sections": 4,
                "judgments_pre2024": 8, "judgments_post2024": 8}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="+", choices=sorted(store.COLLECTIONS))
    args = ap.parse_args()

    print(f"model  : {embedder.model_id()}")
    print(f"store  : {store.chroma_dir()}")
    cli = store.client()
    for name in args.only or list(store.COLLECTIONS):
        t0 = time.time()
        total = sum(1 for _ in store.iter_chunks(name))
        last = [0.0]

        def progress(n, name=name, total=total, t0=t0):
            if time.time() - last[0] > 30 or n == total:
                last[0] = time.time()
                rate = n / max(time.time() - t0, 1e-9)
                print(f"  {name}: {n}/{total}  {rate:.0f}/s", flush=True)

        n = store.build(name, batch_size=256, encode_batch=ENCODE_BATCH[name],
                        cli=cli, progress=progress)
        print(f"{name}: {n} records in {time.time() - t0:.0f}s (count verified)", flush=True)
    embedder.free()
    return 0


if __name__ == "__main__":
    sys.exit(main())
