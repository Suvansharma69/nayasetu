r"""Measure where the insufficient-data threshold belongs.

The guardrail (src/pipeline/guardrail.py) refuses to call the LLM when the best
JUDGMENT match for the facts is too weak. This prints that cosine -- and the
best statute match, the first candidate signal, which did not separate -- for

    in-domain   the 25 Phase 2 case-fact queries (dev + held-out), each in its era
    out-domain  inputs Pramana should refuse: civil and regulatory disputes, and
                text that is not a legal matter at all

and proposes the midpoint of the gap between criminal facts and non-legal text.
Civil/regulatory disputes are printed but excluded from the gap: they overlap
criminal facts on both signals (stuff/docs/phase4_pipeline.md).

It only READS retrieval scores -- it changes nothing about ranking, so scoring
the held-out cases here does not tune retrieval on them. Encoding is on CPU,
exactly as at runtime.

Run:  venv\Scripts\python.exe -u scripts\calibrate_guardrail.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from src.pipeline import guardrail  # noqa: E402
from src.retrieval import embedder, store  # noqa: E402

OUT_OF_DOMAIN = [
    ("civil", "The tenant has not paid rent for six months and the landlord wants to evict him and recover the arrears under the rent agreement."),
    ("civil", "Our company supplied steel under a contract and the buyer has refused to pay the final invoice, citing a delay in delivery."),
    ("civil", "Two brothers dispute the partition of their late father's agricultural land; one claims the will is invalid."),
    ("tax", "The assessing officer disallowed our depreciation claim on plant and machinery for the assessment year 2021-22."),
    ("labour", "The workman was retrenched without one month's notice or retrenchment compensation after eleven years of service."),
    ("family", "The couple wants a divorce by mutual consent and needs to agree custody of their two children."),
    ("not legal", "Preheat the oven to 180 degrees, cream the butter and sugar, then fold in the flour and bake for 25 minutes."),
    ("not legal", "The match went to a super over after both teams scored 176, and the chasing side won off the final ball."),
    ("not legal", "Please summarise the plot of the novel and describe its main characters in about two hundred words."),
    ("not legal", "asdf qwerty lorem ipsum dolor sit amet 12345"),
]


def _scores(text, era, cli):
    return (guardrail.top_judgment_similarity(text, era, cli=cli),
            guardrail.top_statute_similarity(text, era, cli=cli))


def main():
    cli = store.client()
    rows = []  # (group, era, kind, judgment, statute, text)
    for fixture in ("phase2_testset.json", "phase2_heldout.json"):
        for c in json.loads((ROOT / "tests" / "fixtures" / fixture).read_text(encoding="utf-8"))["cases"]:
            rows.append(("in", c["era"], c.get("offence_type"), *_scores(c["query"], c["era"], cli),
                         c["query"]))
    for kind, text in OUT_OF_DOMAIN:
        for era in ("ipc", "bns"):
            rows.append(("out", era, kind, *_scores(text, era, cli), text))
    embedder.free()

    print(f"{'grp':3} era  judgment statute  kind")
    for r in sorted(rows, key=lambda r: -r[3]):
        print(f"{r[0]:3} {r[1]}  {r[3]:.4f}  {r[4]:.4f}  {r[2]:<18} {r[5][:60]}")
    for name, i in (("judgment", 3), ("statute", 4)):
        lo_in = min(r[i] for r in rows if r[0] == "in")
        hi_nl = max(r[i] for r in rows if r[2] == "not legal")
        hi_out = max(r[i] for r in rows if r[0] == "out")
        verdict = (f"separable from non-legal; midpoint {(lo_in + hi_nl) / 2:.4f}"
                   if lo_in > hi_nl else "NOT separable from non-legal")
        print(f"\n{name}: lowest criminal {lo_in:.4f}  highest non-legal {hi_nl:.4f}  "
              f"highest out-of-domain {hi_out:.4f}  -> {verdict}")
    print(f"threshold in use: {guardrail.MIN_JUDGMENT_SIMILARITY}")
    out = ROOT / "stuff" / "docs" / "phase4_guardrail_raw.json"
    out.write_text(json.dumps([{"group": r[0], "era": r[1], "kind": r[2], "top_judgment": r[3],
                                "top_statute": r[4], "query": r[5]} for r in rows], indent=1),
                   encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
