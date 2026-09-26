r"""Phase 3: build the citation graph from data/processed/ and save it.

Then run the Phase 3 gate: 10 real + 10 fabricated section numbers from
tests/fixtures/phase3_adversarial.json must ALL be classified correctly.

Run:  venv\Scripts\python.exe scripts\build_graph.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.graph import citation_graph as cg  # noqa: E402


def main():
    g = cg.build()
    path = cg.save(g)
    print(f"graph -> {path.relative_to(ROOT)}  "
          f"({g.number_of_nodes()} nodes, {g.number_of_edges()} edges)")
    for k, v in sorted(g.graph["stats"].items()):
        print(f"  {k:40} {v}")

    adv = json.loads((ROOT / "tests" / "fixtures" / "phase3_adversarial.json")
                     .read_text(encoding="utf-8"))
    wrong = []
    print("\nPhase 3 gate:")
    for expect, rows in ((True, adv["real"]), (False, adv["fabricated"])):
        for code, sec in rows:
            got = cg.verify_section(g, code, sec)
            ok = got == expect
            wrong += [] if ok else [(code, sec)]
            print(f"  {'ok  ' if ok else 'FAIL'} {code}:{sec:6} "
                  f"{'real' if expect else 'fabricated':10} -> "
                  f"{'verified' if got else 'rejected'}")
    n = len(adv["real"]) + len(adv["fabricated"])
    print(f"\n{n - len(wrong)}/{n} correct -- gate {'PASSES' if not wrong else 'FAILS'}")
    return 0 if not wrong else 1


if __name__ == "__main__":
    sys.exit(main())
