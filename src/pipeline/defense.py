r"""Node 4: defence counter-arguments, plus the final verification pass.

Grounded only in what the pipeline has verified: the charged sections' ingested
statute text, Node 2b's doubts (the ingredient it could not find in the facts),
and Node 3's precedents, which the model may cite only by their [P#] label.
RAG, not fine-tuning (CLAUDE.md Section 2).

Final verification (CLAUDE.md Section 3): every argument is re-checked after
generation. Its target must be a charged section, every precedent label must
name a precedent Node 3 supplied (and that judgment must verify in the graph),
and a quoted fact must appear verbatim in the facts. Nothing is deleted;
failures are listed on the argument as `issues` and it is marked unverified.
"""
from __future__ import annotations

import re

from src.graph import citation_graph as cg

from .applicability import charged, grounded, normalise, statute_text

MAX_ARGUMENTS = 4
STATUTE_CHARS = 700

SCHEMA = {
    "type": "object",
    "properties": {
        "arguments": {
            "type": "array",
            "maxItems": MAX_ARGUMENTS,
            "items": {
                "type": "object",
                "properties": {
                    "against": {"type": "string", "maxLength": 20},
                    "argument": {"type": "string", "maxLength": 600},
                    "fact_quote": {"type": "string", "maxLength": 240},
                    "precedents": {"type": "array", "maxItems": 2,
                                   "items": {"type": "string", "maxLength": 6}},
                },
                "required": ["against", "argument", "fact_quote", "precedents"],
            },
        }
    },
    "required": ["arguments"],
}

_SECTION = re.compile(r"(\d{1,3}[A-Z]{0,3})")
_LABEL = re.compile(r"P\d+")


def build_messages(state, text_of=statute_text):
    era = state["era"].upper()
    doubts = {(a["section"], a["subsection"]): a.get("rule_rejected") or a.get("missing_ingredient")
              for a in state.get("applicability", []) if not a.get("supported")}
    charges = []
    for v in charged(state):
        text = re.sub(r"\s+", " ", text_of(state["era"], v["section"], v.get("subsection")))[:STATUTE_CHARS]
        line = f"- {era} {v.get('subsection') or v['section']} ({v.get('title')}): {text}"
        d = doubts.get((v["section"], v.get("subsection")))
        if d:
            line += f"\n  Reviewer's doubt: {d}"
        charges.append(line)
    precs = [f"[{p['label']}] {p.get('title') or p['doc_id']} ({p.get('court') or 'court n/a'}, "
             f"applies {p['applies']}): {p.get('excerpt') or '(no excerpt: cited by count only)'}"
             for p in state.get("precedents", [])]
    system = (
        "You assist DEFENCE counsel in an Indian criminal case. Write up to "
        f"{MAX_ARGUMENTS} concrete counter-arguments against the charges listed. Rules:\n"
        "- Each argument targets exactly one listed charge: put its section number in `against`.\n"
        "- Attack an ingredient of that section's text that the facts do not clearly establish, "
        "or a gap in evidence the prosecution must fill. Use the reviewer's doubts where given.\n"
        "- `fact_quote`: copy the exact words from the facts that the argument turns on, or \"\".\n"
        "- `precedents`: only labels like P1 from the list below, and only if that precedent "
        "is genuinely relevant to the argument; otherwise an empty list. Never name any other case.\n"
        "- Never cite a section that is not in the list of charges.\n"
        "- Plain, specific legal English. No preamble."
    )
    user = (f"FACTS:\n{state['case_facts']}\n\nCHARGES ({era}):\n" + "\n".join(charges)
            + "\n\nPRECEDENTS:\n" + ("\n".join(precs) if precs else "(none)"))
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def verify_arguments(state, raw, g):
    """Final verification pass over Node 4's output."""
    charged = {v["section"] for v in state["verified_sections"]}
    charged |= {v["subsection"] for v in state["verified_sections"] if v.get("subsection")}
    by_label = {p["label"]: p for p in state.get("precedents", [])}
    facts_norm = normalise(state["case_facts"])
    out = []
    for a in raw:
        issues = []
        m = _SECTION.search(str(a.get("against", "")).upper())
        target = m.group(1) if m else None
        sub = re.search(r"\d{1,3}[A-Z]{0,3}\(\d+\)", str(a.get("against", "")).upper())
        if not target or (target not in charged and (not sub or sub.group(0) not in charged)):
            issues.append(f"targets {a.get('against')!r}, which is not a verified charge")
        cited = []
        for lab in a.get("precedents") or []:
            lm = _LABEL.search(str(lab).upper())
            p = by_label.get(lm.group(0)) if lm else None
            if p is None or not cg.verify_case(g, p["doc_id"]):
                issues.append(f"cites {lab!r}, which is not a supplied, verified precedent")
            else:
                cited.append({"label": p["label"], "doc_id": p["doc_id"], "title": p.get("title")})
        quote = str(a.get("fact_quote") or "").strip()
        if quote and not grounded(quote, facts_norm):
            issues.append("its quoted fact does not appear in the facts")
            quote = ""
        out.append({"against": f"{state['era'].upper()} {target}" if target else a.get("against"),
                    "argument": str(a.get("argument", "")).strip(), "fact_quote": quote,
                    "precedents": cited, "verified": not issues, "issues": issues})
    return out


def defense_generator(state, llm, g, text_of=statute_text):
    """Node 4 + the final verification pass. {"defenses": [...]}."""
    if not state["verified_sections"]:
        return {"defenses": []}
    reply = llm(build_messages(state, text_of), SCHEMA)
    return {"defenses": verify_arguments(state, reply.get("arguments") or [], g)}
