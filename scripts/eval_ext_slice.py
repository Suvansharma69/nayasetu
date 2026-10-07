"""Phase 6's pipeline evaluation on a chosen slice of the external set, into a chosen file.

    python scripts/eval_ext_slice.py OUT.jsonl START N

Same cases, same scoring record as scripts/eval_phase6.py (seeded shuffle of
Hanno-Labs/indian-ipc-statute-identification); only the slice and the output
file differ. Resumable: cases already in OUT are skipped. Used for the
2026-10-07 accuracy A/B on ext0060-0089, cases no one had read
(scripts/run_accuracy_ext.bat).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import eval_phase6 as e  # noqa: E402

if __name__ == "__main__":
    out, start, n = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    e.run_pipeline(n, 0, start=start, path=out)
