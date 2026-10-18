r"""Out-of-domain probes: non-legal text is stopped; civil disputes are flagged.

The ten inputs are exactly those scripts/calibrate_guardrail.py measured
(civil, tax, labour and family disputes; text that is not legal at all), run
through the full pipeline with a BNS-era date. Expected outcome per kind:

    not legal                      insufficient_data  (the guardrail, no LLM call)
    civil / tax / labour / family  a "may not disclose a criminal offence" WARNING on the
                                   report (since 2026-10-01 the model can no longer decline
                                   a case outright; sections it finds are still shown)
                                   or insufficient_data

A non-legal probe that ends with any charge fails; a civil probe fails only if the
report carries no warning. Results: stuff/docs/probes_raw.json.

Run:  venv\Scripts\python.exe -u scripts\eval_probes.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from calibrate_guardrail import OUT_OF_DOMAIN  # noqa: E402
from src.graph import citation_graph as cg  # noqa: E402
from src.pipeline import graph as pipeline  # noqa: E402
from src.retrieval import embedder, store  # noqa: E402

WARNING = "may not disclose a criminal offence"


def main():
    g, cli = cg.load(), store.client()
    rows, ok = [], 0
    for kind, text in OUT_OF_DOMAIN:
        out = pipeline.run(text, "2024-09-01", g=g, cli=cli)
        warned = any(WARNING in w for w in out["state"].get("warnings", []))
        if kind == "not legal":
            passed = out["status"] == "insufficient_data" and not out.get("charges")
        else:
            passed = out["status"] == "insufficient_data" or warned
        ok += passed
        why = (out["state"].get("facts_profile") or {}).get("why") or (out.get("guardrail") or {}).get("reason")
        rows.append({"kind": kind, "text": text, "status": out["status"], "passed": passed,
                     "charges": [v["section"] for v in out.get("charges", [])], "why": why})
        print(f"{'PASS' if passed else 'FAIL'}  {kind:<10} {out['status']:<22} "
              f"charges={rows[-1]['charges']}  {str(why)[:90]}", flush=True)
    embedder.free()
    print(f"\n{ok}/{len(rows)} probes handled correctly")
    (ROOT / "stuff" / "docs" / "probes_raw.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
