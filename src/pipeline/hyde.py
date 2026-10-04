r"""HyDE for statute retrieval: restate the facts in a statute's own register.

Phase 2 measured the weak link of statute retrieval: case facts are narrative
("the accused pushed the motorcycle away down the lane") while statutes are
abstract ("whoever, intending to take dishonestly any movable property out of
the possession of any person without that person's consent, moves that
property..."). Hypothetical Document Embeddings (Gao et al., 2022) closes that
gap by asking an LLM to write the query in the target documents' style and
embedding THAT. Judgments are narrative too, so precedent votes keep using the
raw facts; only the statute side uses the restatement.

What stops this from becoming a hallucination channel:
* The restatement is only ever a SEARCH QUERY. It is never shown, never
  verified, never cited; every section still comes from the ingested index and
  passes Node 2.
* The model is told not to name sections or statutes, and every digit is
  stripped from what it writes anyway -- so a remembered "Section 379" cannot
  steer the search toward a number rather than toward meaning.
"""
from __future__ import annotations

import re

SCHEMA = {
    "type": "object",
    "properties": {"restatement": {"type": "string", "maxLength": 700}},
    "required": ["restatement"],
}

SYSTEM = (
    "Restate the facts of a criminal complaint in the abstract, general language that a penal "
    "statute uses: who did what act, with what intention or knowledge, to whom or to what "
    "property, by what means, and with what result -- for example 'the accused dishonestly took "
    "movable property out of the possession of another person without that person's consent'. "
    "Keep every legally relevant element of the facts; drop names, dates and places. Do NOT "
    "name or number any section, code or statute. Two to four sentences.")


def restate(case_facts, llm):
    """The facts in statute register, digits stripped; '' if the model gives nothing."""
    reply = llm([{"role": "system", "content": SYSTEM},
                 {"role": "user", "content": case_facts}], SCHEMA)
    text = str(reply.get("restatement") or "")
    return re.sub(r"\s+", " ", re.sub(r"\d+", " ", text)).strip()
