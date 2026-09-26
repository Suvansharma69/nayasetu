r"""Download Supreme Court judgments from the vanga open-data S3 bucket.

Source
------
s3://indian-supreme-court-judgments (AWS Open Data, ap-south-1, public --
no credentials, plain anonymous HTTPS). Laid out exactly as CLAUDE.md
Section 4 rule 1 describes: partitioned by year.

    data/tar/year=<Y>/english/english.tar      <- judgment text, what we want
    data/tar/year=<Y>/regional/regional.tar    <- Indian-language translations
    metadata/parquet/year=<Y>/metadata.parquet <- title/judge/citation/date/...

What this pulls, and why it is much smaller than Section 4 budgeted
-------------------------------------------------------------------
English only. The `regional` tars are ~1-2 GB per year of translations of the
same judgments into Hindi/Punjabi/Odia/etc. Pramana is an English-language
system end to end (InLegal-Sbert is English-only), so they are pure cost.
Dropping them takes 2023+2024 from the budgeted 4-5 GB down to ~604 MB.

Years: 2023, 2024, 2025. Section 4 originally said "2023 and 2024 only".
2025 was added deliberately -- see CLAUDE.md Known Gotchas. In short: BNS
applies to offences on/after 2024-07-01, and nothing charged under BNS had
reached a Supreme Court judgment by Dec 2024, so without 2025 the
`judgments_post2024` collection contains no BNS-citing judgment at all.

Resume
------
Unlike huggingface_hub (which never resumes -- see fetch_models.py), S3 honours
HTTP Range, so a killed transfer genuinely picks up where it stopped. That
matters on this link: measured 18 KB/s to 660 KB/s minutes apart. Partial files
are written as <name>.part and only renamed once the byte count matches the
Content-Length from S3, so a truncated file can never be mistaken for a
complete one.

Run:  venv\Scripts\python.exe scripts\fetch_judgments.py
      venv\Scripts\python.exe scripts\fetch_judgments.py --years 2025
      venv\Scripts\python.exe scripts\fetch_judgments.py --check   (sizes only)
"""
import argparse
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "data" / "raw" / "judgments"

BUCKET = "https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com"
YEARS = [2023, 2024, 2025]

# (key template, local filename template). English tar + its index + metadata.
# The index json maps tar members -> case paths; it is 30 KB and saves us
# walking the whole tar just to find out what is in it.
ARTIFACTS = [
    ("data/tar/year={y}/english/english.tar", "english_{y}.tar"),
    ("data/tar/year={y}/english/english.index.json", "english_{y}.index.json"),
    ("metadata/parquet/year={y}/metadata.parquet", "metadata_{y}.parquet"),
]


def remote_size(key):
    """Content-Length for an S3 key, via HEAD. None if the key is absent."""
    req = urllib.request.Request(f"{BUCKET}/{key}", method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return int(r.headers["Content-Length"])
    except Exception:
        return None


def human(n):
    return f"{n / 1e6:,.1f} MB" if n is not None else "?"


def fetch(key, out, expect, attempts=40):
    """Resumable download. Returns True once out exists at the expected size."""
    if out.exists() and out.stat().st_size == expect:
        print(f"  [have] {out.name}  {human(expect)}")
        return True

    part = out.with_suffix(out.suffix + ".part")
    for attempt in range(1, attempts + 1):
        have = part.stat().st_size if part.exists() else 0
        if have > expect:
            # Ranged resume against a changed object would corrupt silently.
            print(f"  [warn] {part.name} is larger than remote; restarting")
            part.unlink()
            have = 0
        print(
            f"  [get ] {out.name}  attempt {attempt}/{attempts}"
            f"  from {human(have)} / {human(expect)}"
        )
        # curl, not urllib: it handles Range resume, retry-on-reset and the
        # progress meter without us reimplementing any of it.
        rc = subprocess.call([
            "curl", "-sSL", "--fail",
            "-C", "-",                 # resume at existing byte count
            "--retry", "5", "--retry-delay", "5", "--retry-all-errors",
            "--connect-timeout", "30",
            "--speed-time", "120", "--speed-limit", "1024",  # stall => die, retry
            "-o", str(part), f"{BUCKET}/{key}",
        ])
        size = part.stat().st_size if part.exists() else 0
        if size == expect:
            part.replace(out)
            print(f"  [done] {out.name}  {human(size)}")
            return True
        print(f"  [part] rc={rc}  {human(size)} / {human(expect)}")
        time.sleep(min(5 * attempt, 60))
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="*", type=int, default=YEARS)
    ap.add_argument("--check", action="store_true", help="print sizes, download nothing")
    ap.add_argument("--attempts", type=int, default=40)
    args = ap.parse_args()

    DEST.mkdir(parents=True, exist_ok=True)
    plan, total = [], 0
    for y in args.years:
        for key_t, name_t in ARTIFACTS:
            key = key_t.format(y=y)
            sz = remote_size(key)
            if sz is None:
                print(f"[miss] {key}")
                continue
            plan.append((key, DEST / name_t.format(y=y), sz))
            total += sz

    print(f"\n{len(plan)} objects, {human(total)} total\n")
    if args.check:
        for key, out, sz in plan:
            print(f"  {human(sz):>12}  {key}")
        return 0

    failed = [out.name for key, out, sz in plan if not fetch(key, out, sz, args.attempts)]
    on_disk = sum(p.stat().st_size for p in DEST.glob("*") if p.is_file())
    print(f"\n{DEST}: {human(on_disk)} on disk")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("all objects complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
