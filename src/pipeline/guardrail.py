r"""The insufficient-data guardrail (CLAUDE.md Section 2).

If retrieval finds nothing relevant above threshold, the pipeline returns an
explicit "insufficient data" answer and never calls the LLM: a 4B model handed
weak context does not say "I don't know", it writes something plausible.

The signal, chosen by measurement (scripts/calibrate_guardrail.py,
docs/phase4_pipeline.md), is the cosine similarity of the best-matching
JUDGMENT chunk in the era's judgment collections -- not the best statute:

* Best statute match did not separate anything. BGE-M3's statute cosines are
  compressed into ~0.32-0.60 and a landlord-tenant rent dispute (0.537)
  outscored ten of the 25 real criminal fact patterns.
* Best judgment match separates non-legal input cleanly: every criminal fact
  pattern >= 0.595, every non-legal input <= 0.557. Facts are narrative and so
  are judgments, which is the same reason precedent votes help the ranker.

What it does NOT do: tell a civil dispute from a criminal one. Contract,
tenancy, tax, labour and family disputes scored 0.60-0.63, inside the criminal
range -- that distinction is semantic, and faking it with a threshold would
refuse real cases. Node 1 is told to return no sections when the facts disclose
no offence, and the pipeline reports that as its own explicit status.
"""
from __future__ import annotations

import os

from src.retrieval import ranker, store

# Midpoint of the measured gap (0.557 highest non-legal, 0.595 lowest criminal),
# 2026-09-27. Re-measure with scripts/calibrate_guardrail.py if the corpus or
# embedder changes; never tune it on the gate cases.
MIN_JUDGMENT_SIMILARITY = float(os.environ.get("MIN_JUDGMENT_SIMILARITY", "0.576"))


def top_judgment_similarity(case_facts, era, cli=None, device="cpu"):
    best = 0.0
    for collection in ranker.ERA[era]["judgments"]:
        hits = store.retrieve(case_facts, collection, top_k=1, cli=cli, device=device)
        if hits:
            best = max(best, hits[0]["score"])
    return best


def top_statute_similarity(case_facts, era, cli=None, device="cpu"):
    """Recorded for the calibration table; not the decision signal (see above)."""
    hits = store.retrieve_sections(case_facts, ranker.ERA[era]["statutes"], top_k=1,
                                   cli=cli, device=device)
    return hits[0]["score"] if hits else 0.0


def check(case_facts, era, cli=None, device="cpu", threshold=None):
    """(sufficient, detail). `detail` records the score and threshold used."""
    t = MIN_JUDGMENT_SIMILARITY if threshold is None else threshold
    if not case_facts or not case_facts.strip():
        return False, {"reason": "no case facts given", "top_similarity": None, "threshold": t}
    score = top_judgment_similarity(case_facts, era, cli=cli, device=device)
    ok = score >= t
    return ok, {"reason": None if ok else (
                    f"the closest ingested judgment scores {score:.3f}, below the {t:.3f} "
                    "relevance threshold: nothing in the corpus resembles these facts closely "
                    "enough to ground an answer"),
                "top_similarity": score, "threshold": t}
