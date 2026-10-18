r"""Intake: turn a pasted court order or FIR into a statement of the alleged facts.

Phase 6 (stuff/docs/evaluation_results.md) measured the system on real Patna High
Court orders: a right section was charged in 12/30, against 60-100% on written
fact statements. The orders are mostly procedure -- counsel, bail, custody, case
numbers -- and the facts are often one sentence. That vocabulary steered
retrieval to procedural sections (229A, 174A, 188) and Node 1 charged IPC 438
because the order discussed "anticipatory bail under Section 438" (the CrPC).

So, before anything else runs:

* `looks_procedural` decides, deterministically, whether the input reads like a
  court order or FIR. A plain fact statement is passed through untouched -- no
  LLM call, no change in behaviour, no added time.
* Otherwise one LLM call restates only what the accused is alleged to have done.
  It is told to drop procedure and every section/case number, and to add nothing.
* The restatement is checked: if too few of its content words occur in the
  original, it may have invented facts, and the original is used instead.

The original text is kept (`original_input`) and the report shows both.
"""
from __future__ import annotations

import re

MARKERS = [
    r"\blearned (?:senior )?counsel", r"\bpetitioner", r"\bopposite part", r"\bbail\b",
    r"\banticipatory", r"\bP\.\s?S\.?\s?Case", r"\bpolice station\b", r"\bF\.?I\.?R\b", r"\bCr\.?\s?P\.?\s?C",
    r"\bu/s\b", r"\bapprehending (?:his |their )?arrest", r"\bin custody\b", r"\bcharge[- ]?sheet",
    r"\bchargesheet", r"\bHon'?ble\b", r"\bheard\b", r"\bA\.?P\.?P\b", r"\bpublic prosecutor",
    r"\bcase (?:no|number)\b", r"\bsessions trial\b", r"\bappellant", r"\brespondent",
]
_MARKERS = [re.compile(m, re.I) for m in MARKERS]
MIN_MARKERS = 3
MIN_OVERLAP = 0.6

SCHEMA = {
    "type": "object",
    # Facts before the flag: asked first, qwen3.5:4b answered "no facts" for 8 of
    # 10 orders, including one whose abduction it had just extracted correctly.
    "properties": {"alleged_facts": {"type": "string", "maxLength": 1200},
                   "facts_stated": {"type": "boolean"}},
    "required": ["alleged_facts", "facts_stated"],
}

SYSTEM = (
    "You read Indian court orders, FIRs and complaints and extract the ALLEGED FACTS of the offence. "
    "Write a short plain-English statement (3-8 sentences) of what the accused is alleged to have "
    "done: the acts, the weapons, the injuries or death, the property, the persons and their "
    "relationships, and how many accused acted together.\n"
    "Rules:\n"
    "- Leave out all court procedure: counsel, bail, custody, arrest, hearings, trial progress, "
    "witnesses turning hostile, the court's reasoning and orders.\n"
    "- Never write any section number, Act name, case number or police-station case number.\n"
    "- Add nothing that the text does not say. If the text gives only one line of facts, write one line.\n"
    "- Do not judge guilt; state the allegations as allegations.\n"
    "- facts_stated: false if the text describes no act of the accused at all (only procedure); "
    "then leave alleged_facts empty."
)

_WORD = re.compile(r"[a-z]{4,}")
_STOP = {"that", "with", "from", "this", "were", "have", "been", "they", "their", "which", "when",
         "after", "into", "also", "there", "against", "allegedly", "alleged", "accused", "complainant"}


def markers(text):
    return [m.pattern for m in _MARKERS if m.search(text or "")]


def looks_procedural(text):
    return len(markers(text)) >= MIN_MARKERS


def overlap(extracted, original):
    """Share of the extraction's content words that occur in the original."""
    words = [w for w in _WORD.findall(extracted.lower()) if w not in _STOP]
    if not words:
        return 0.0
    src = set(_WORD.findall(original.lower()))
    return sum(1 for w in words if w in src) / len(words)


def extract(text, llm):
    """{"facts", "extracted": bool, "why"}. Never raises on a bad extraction:
    the original text is the fallback."""
    if not looks_procedural(text):
        return {"facts": text, "extracted": False, "why": "reads as a fact statement"}
    reply = llm([{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}], SCHEMA)
    facts = re.sub(r"\s+", " ", str(reply.get("alleged_facts") or "")).strip()
    # "No facts" only when the flag AND an empty extraction agree: a single
    # boolean never erases the rest of the answer (Known Gotchas, 2026-09-27).
    if reply.get("facts_stated") is False and len(facts) < 20:
        return {"facts": text, "extracted": False, "no_facts": True,
                "why": "the text states no alleged facts, only procedure"}
    if len(facts) < 20:
        return {"facts": text, "extracted": False, "why": "the extraction was empty; original used"}
    share = overlap(facts, text)
    if share < MIN_OVERLAP:
        return {"facts": text, "extracted": False,
                "why": f"only {share:.0%} of the extraction's words occur in the input; original used"}
    return {"facts": facts, "extracted": True, "why": f"court order/FIR detected ({len(markers(text))} markers)"}
