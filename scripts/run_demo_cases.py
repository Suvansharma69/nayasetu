r"""Run the demo cases through the full pipeline and save their reports.

The Streamlit app shows these instantly (a full run takes 2-3 minutes on this
laptop); "Run live" in the app goes through the same pipeline via FastAPI.

Run:  venv\Scripts\python.exe scripts\run_demo_cases.py [case-id ...]
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from src.api import report  # noqa: E402
from src.pipeline import graph  # noqa: E402

CASES = ROOT / "app" / "samples" / "cases.json"
OUT = ROOT / "app" / "samples"


def main(ids):
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    for c in cases:
        if ids and c["id"] not in ids:
            continue
        t = time.perf_counter()
        res = graph.run(c["facts"], c["offence_date"], full=True)
        rep = report.build(res)
        rep["sample"] = {"id": c["id"], "name": c["name"]}
        (OUT / f"{c['id']}.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False, default=str),
                                             encoding="utf-8")
        print(f"{c['id']}: {rep['status']} charges={[x['section'] for x in rep.get('charges', [])]} "
              f"precedents={len(rep.get('precedents', []))} defenses={len(rep.get('defenses', []))} "
              f"{time.perf_counter() - t:.0f}s", flush=True)


if __name__ == "__main__":
    main(set(sys.argv[1:]))
