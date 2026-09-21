r"""Download the embedding models into D:\hf-cache, resiliently.

Why this is a script and not a one-liner
----------------------------------------
Three separate things go wrong fetching models on this machine, and all three
must be handled before the first byte moves:

1. Xet.  huggingface_hub defaults to the Xet chunk protocol (hf_xet is
   installed). It stalled outright here -- the cache grew 3.2MB -> 3.6MB over
   several minutes while a plain curl of the same resolve/ URL pulled
   ~480 KB/s. HF_HUB_DISABLE_XET forces the classic HTTP path.
2. Symlinks.  Windows without Developer Mode cannot symlink, so hub dies with
   WinError 1314 when linking blobs into snapshots/. HF_HUB_DISABLE_SYMLINKS
   forces plain copies. Note the _WARNING variant does NOT do this.
3. The link.  Highly variable (measured 18 KB/s to 484 KB/s against different
   hosts minutes apart) and it drops entirely (getaddrinfo failed). Retries
   with backoff are mandatory, and an interrupted download NEVER resumes --
   hub names its temp file <etag>.<uuid4>.incomplete, fresh per process
   (PR #4228), so every attempt restarts from zero.

All three env vars are read by huggingface_hub at IMPORT time, so they are set
above the import below. Do not move the import to the top of the file.

Run:  venv\Scripts\python.exe scripts\fetch_models.py
      venv\Scripts\python.exe scripts\fetch_models.py --challenger
      venv\Scripts\python.exe scripts\fetch_models.py --attempts 50
"""
import argparse
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

os.environ.setdefault("HF_HOME", r"D:\hf-cache")
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from huggingface_hub import snapshot_download          # noqa: E402
import huggingface_hub.constants as hub_constants      # noqa: E402


def cache_mb():
    root = os.environ["HF_HOME"]
    total = 0
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total / 1024 ** 2


def start_progress_thread(interval=30):
    """The Xet-disabled path does grow the .incomplete blob, but the whole-cache
    number is the one that stays meaningful if Xet ever comes back on."""
    def loop():
        prev = cache_mb()
        while True:
            time.sleep(interval)
            cur = cache_mb()
            print(f"    {cur:7.1f} MB cached  ({(cur - prev) * 1024 / interval:+.0f} KB/s)",
                  flush=True)
            prev = cur
    threading.Thread(target=loop, daemon=True).start()


def clear_incomplete(repo_id):
    """Orphaned bytes from a killed attempt are never reused - drop them so the
    cache size reported above reflects real progress."""
    d = Path(os.environ["HF_HOME"]) / "hub" / ("models--" + repo_id.replace("/", "--")) / "blobs"
    for f in d.glob("*.incomplete") if d.is_dir() else []:
        try:
            f.unlink()
        except OSError:
            pass


def fetch(repo_id, attempts):
    for n in range(1, attempts + 1):
        try:
            print(f"--- {repo_id}: attempt {n}/{attempts} ---", flush=True)
            path = snapshot_download(repo_id, max_workers=1)
            print(f"OK  {repo_id} -> {path}", flush=True)
            return True
        except Exception as e:
            print(f"    attempt {n} failed: {type(e).__name__}: {e}", flush=True)
            clear_incomplete(repo_id)
            backoff = min(15 * n, 120)
            print(f"    retrying in {backoff}s", flush=True)
            time.sleep(backoff)
    print(f"FAILED  {repo_id} after {attempts} attempts", flush=True)
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--challenger", action="store_true",
                    help="also fetch EMBEDDING_CHALLENGER (BGE-M3, ~2.3GB - much "
                         "bigger than the incumbent; only needed at the Phase 2 gate)")
    ap.add_argument("--attempts", type=int, default=20)
    ap.add_argument("--models", nargs="+",
                    help="override: fetch exactly these repo ids")
    args = ap.parse_args()

    if args.models:
        repos = args.models
    else:
        repos = [os.environ.get("EMBEDDING_MODEL", "bhavyagiri/InLegal-Sbert")]
        if args.challenger:
            repos.append(os.environ.get("EMBEDDING_CHALLENGER", "BAAI/bge-m3"))

    for r in repos:
        assert "InLegalBERT" not in r, (
            f"{r} is the base MLM model, not the Sbert variant - it has no trained "
            "pooling layer and loads WITHOUT error while giving bad embeddings. "
            "See CLAUDE.md Known Gotchas."
        )

    print(f"cache   : {os.environ['HF_HOME']}  ({cache_mb():.1f} MB now)")
    print(f"xet off : {hub_constants.HF_HUB_DISABLE_XET}   "
          f"symlinks off: {hub_constants.HF_HUB_DISABLE_SYMLINKS}")
    print(f"models  : {', '.join(repos)}\n", flush=True)

    start_progress_thread()
    failed = [r for r in repos if not fetch(r, args.attempts)]

    print(f"\ncache now {cache_mb():.1f} MB")
    if failed:
        print("could not fetch: " + ", ".join(failed))
        print("The link here drops out; re-run this script when it is back up.")
        return 1
    print("all models present - re-run scripts/check_env.py to verify they load")
    return 0


if __name__ == "__main__":
    sys.exit(main())
