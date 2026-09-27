r"""Download the IL-TUR evaluation splits Phase 6 needs (LSI and PCR), nothing more.

Source: huggingface.co/datasets/Exploration-Lab/IL-TUR -- GATED. The account
behind HF_TOKEN must have accepted the dataset's terms on the website, or every
request returns 403 (401 without a token). That acceptance is a person's action
on their own account; no script can do it.

What is pulled, and what is not
-------------------------------
    lsi/{dev,test,statutes}             Legal Statute Identification  ~87 MB
    pcr/{dev,test}_{queries,candidates} Prior Case Retrieval          ~67 MB
The train splits (~1.2 GB of the 1.6 GB repo) are NOT pulled: they exist to
train models, and this project does RAG, not fine-tuning (CLAUDE.md Section 2).
Nor is any other IL-TUR task.

Resume
------
huggingface_hub never resumes (CLAUDE.md Known Gotchas), so this does not use
it. The resolve URLs honour HTTP Range: bytes land in <name>.part and the file
is renamed only once its size equals the size the HF API lists for it.

Run:  venv\Scripts\python.exe scripts\fetch_iltur.py
      venv\Scripts\python.exe scripts\fetch_iltur.py --check   (sizes + access only)
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "data" / "raw" / "iltur"
REPO = "Exploration-Lab/IL-TUR"
BASE = f"https://huggingface.co/datasets/{REPO}/resolve/main/"
WANT = [
    "README.md",            # holds the LSI label names (class id -> "Section 302"); public
    "lsi/statutes-00000-of-00001.parquet",
    "lsi/dev-00000-of-00001.parquet",
    "lsi/test-00000-of-00001.parquet",
    "pcr/dev_queries-00000-of-00001.parquet",
    "pcr/dev_candidates-00000-of-00001.parquet",
    "pcr/test_queries-00000-of-00001.parquet",
    "pcr/test_candidates-00000-of-00001.parquet",
]


def token():
    tok = os.environ.get("HF_TOKEN")
    if not tok and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("HF_TOKEN="):
                tok = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not tok:
        sys.exit("HF_TOKEN is not set (.env or environment) -- IL-TUR is gated.")
    return tok


def sizes():
    """{path: bytes} from the public tree API (metadata is public even when content is gated)."""
    url = f"https://huggingface.co/api/datasets/{REPO}/tree/main?recursive=true"
    with urllib.request.urlopen(url, timeout=60) as r:
        tree = json.load(r)
    return {f["path"]: f.get("lfs", {}).get("size", f.get("size")) for f in tree if f["type"] == "file"}


def fetch(path, size, tok, attempts=40):
    out = DEST / path
    if out.exists() and out.stat().st_size == size:
        print(f"  [have] {path}")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    for attempt in range(1, attempts + 1):
        have = part.stat().st_size if part.exists() else 0
        if have == size:
            break
        req = urllib.request.Request(BASE + path, headers={"Authorization": f"Bearer {tok}",
                                                           "Range": f"bytes={have}-"})
        print(f"  [get ] {path}  attempt {attempt}/{attempts}  from {have / 1e6:.1f} / {size / 1e6:.1f} MB",
              flush=True)
        try:
            with urllib.request.urlopen(req, timeout=120) as r, part.open("ab") as fh:
                if have and r.status != 206:           # server ignored Range: start over
                    fh.truncate(0)
                while chunk := r.read(1 << 20):
                    fh.write(chunk)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                sys.exit(f"  HTTP {e.code}: accept the terms at https://huggingface.co/datasets/{REPO} "
                         "with the account that owns HF_TOKEN, then re-run.")
            print(f"  HTTP {e.code}; retrying", flush=True)
            time.sleep(min(60, 5 * attempt))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            print(f"  {e!r}; retrying", flush=True)
            time.sleep(min(60, 5 * attempt))
    if not part.exists() or part.stat().st_size != size:
        sys.exit(f"  {path}: incomplete after {attempts} attempts -- re-run to resume")
    part.replace(out)
    print(f"  [done] {path}  {size / 1e6:.1f} MB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    tok, listed = token(), sizes()
    missing = [p for p in WANT if p not in listed]
    if missing:
        sys.exit(f"not in the repo any more: {missing}")
    print(f"{len(WANT)} files, {sum(listed[p] for p in WANT) / 1e6:.1f} MB")
    if args.check:
        # Probe a GATED data file. The README is public, so probing it reports
        # "OK" without access -- which is exactly the false OK this once gave.
        gated = next(p for p in WANT if p.endswith(".parquet"))
        req = urllib.request.Request(BASE + gated, method="HEAD", headers={"Authorization": f"Bearer {tok}"})
        try:
            urllib.request.urlopen(req, timeout=60)
            print("access: OK")
        except urllib.error.HTTPError as e:
            print(f"access: HTTP {e.code} -- terms not accepted for this token's account" if e.code == 403
                  else f"access: HTTP {e.code}")
        return
    for p in WANT:
        fetch(p, listed[p], tok)
    print(f"all files complete in {DEST}")


if __name__ == "__main__":
    main()
