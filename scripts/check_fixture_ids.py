r"""Check every section id in a test fixture against the INGESTED statutes.

A fixture's `relevant` / `arguable` lists are only meaningful if each id names a
real section of the case's own code (never the other code -- the union error).
This prints each id with its ingested title and the opening of its text, so the
assignment can be read against the statute, and fails on any id that does not
exist or belongs to the wrong era.

Run:  venv\Scripts\python.exe scripts\check_fixture_ids.py tests\fixtures\broad_coverage.json
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = {"ipc": "statutes_ipc.jsonl", "bns": "statutes_bns.jsonl"}


def main(path):
    stat = {code: {c["chunk_id"]: c for c in map(json.loads, (ROOT / "data" / "processed" / f)
                                                   .read_text(encoding="utf-8").splitlines())}
            for code, f in FILES.items()}
    bad = 0
    for case in json.loads(Path(path).read_text(encoding="utf-8"))["cases"]:
        print(f"\n#{case.get('id')} [{case['era']}] {case.get('offence_type')}")
        for kind in ("relevant", "arguable"):
            for cid in case.get(kind, []):
                code = cid.split("_s", 1)[0]
                c = stat.get(code, {}).get(cid)
                if code != case["era"] or c is None:
                    bad += 1
                    print(f"  !! {kind:8} {cid}: {'wrong era' if c else 'NOT an ingested section'}")
                    continue
                text = re.sub(r"\s+", " ", c["text"])[:110]
                print(f"  {kind:8} {cid:10} {c.get('section_title')!s:45.45} | {text}")
    print(f"\n{bad} bad ids")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
