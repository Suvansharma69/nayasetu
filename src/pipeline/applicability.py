r"""Node 2b: does each VERIFIED section actually apply to these facts?

Node 2 proves a section exists in the routed code. That is necessary and not
sufficient: at Phase 4 real-but-inapplicable sections verified routinely (IPC
302 on a dowry death, BNS 66-68 on a fraud, IPC 25's definition of
"fraudulently" on a forgery). This node asks the model, with the section's
INGESTED statute text in front of it (RAG -- no fine-tuning, CLAUDE.md
Section 2), to show which facts establish the offence and which ingredient, if
any, the facts do not show.

The model's word is not taken on trust, for the same reason Node 2 exists:

* Every supporting quote must be an exact substring of the facts (after
  normalising case, whitespace and quote marks). A quote the model invented or
  paraphrased is dropped and recorded as dropped.
* A section is `supported` only if the model says it applies AND at least one
  quote survives AND the model named no missing ingredient.

Nothing is deleted. verified_sections is untouched; each entry gets an
`applicability` record, and the report shows supported charges apart from
verified-but-unsupported sections.
"""
from __future__ import annotations

import re

from src.retrieval import ranker, store

MAX_STATUTE_CHARS = 1200

SCHEMA = {
    "type": "object",
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string", "maxLength": 20},
                    # Evidence before verdict. Field order and wording were
                    # chosen on the Phase 2 DEV set only (2026-09-27), from three
                    # measured variants (relevant kept / extras removed):
                    #   quotes first, neutral wording            14/16  13/28  <- this
                    #   missing first, "usually one or two apply"  9/16  24/28
                    #   missing first, neutral wording            11/16  17/28
                    # Asking for the missing ingredient first made qwen3.5:4b
                    # hyper-literal and legally wrong (a fracture "not shown" to
                    # be grievous hurt, which IPC 320 says it is). Losing the
                    # right charge is the worse error, and unsupported sections
                    # are shown, not deleted -- so recall wins.
                    "facts_quotes": {"type": "array", "maxItems": 3,
                                     "items": {"type": "string", "maxLength": 240}},
                    "missing_ingredient": {"type": "string", "maxLength": 240},
                    "applies": {"type": "boolean"},
                },
                "required": ["section", "facts_quotes", "missing_ingredient", "applies"],
            },
        }
    },
    "required": ["assessments"],
}

# How a model says "no ingredient is missing" instead of leaving the field empty.
_NOTHING_MISSING = {"", "none", "n/a", "na", "nil", "nothing", "no", "-", "none missing",
                    "no ingredient is missing", "all ingredients are shown", "not applicable"}

_ALL_SHOWN = re.compile(r"^(none|nil|n/?a)\b|^(nothing|no (essential )?ingredient)( is)? missing\b"
                        r"|\ball (the )?(essential )?ingredients (are|were) (present|shown|established|met|satisfied)")


def nothing_missing(text):
    """True when the model's `missing_ingredient` says nothing is missing --
    "", "None", "None; all ingredients are present." (measured), "N/A"..."""
    t = normalise(text).strip(" .")
    return t in _NOTHING_MISSING or bool(_ALL_SHOWN.search(t))


_REF = re.compile(r"(?<![\d.])(\d{1,3}[A-Z]{0,3})(?![\dA-Z])")

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def normalise(text):
    return re.sub(r"\s+", " ", (text or "").translate(_QUOTES)).strip().lower()


def grounded(quote, facts_norm):
    q = normalise(quote).strip(" .,;:\"'")
    return len(q) >= 8 and q in facts_norm


# Ingredients that are a headcount, written into the statutes themselves, so a
# rule decides them instead of the model: an unlawful assembly is "five or more
# persons" (IPC 141 / BNS 189(1)), and common intention, conspiracy and joint
# liability need at least two. Applied only when Node 1 reported how many
# accused there were (accused_count >= 1; 0 means the facts do not say).
MIN_PERSONS = {
    "ipc": {**{s: 5 for s in ("141", "142", "143", "144", "145", "146", "147", "148", "149")},
            "34": 2, "120A": 2, "120B": 2},
    "bns": {"189": 5, "190": 5, "191": 5, "3": 2, "61": 2},
}


def headcount_rule(era, section, profile):
    """A reason string if the reported headcount rules the section out, else None."""
    need = MIN_PERSONS.get(era, {}).get(section)
    n = (profile or {}).get("accused_count")
    if need and isinstance(n, int) and 1 <= n < need:
        what = "an unlawful assembly needs five or more persons" if need == 5 else \
            "joint liability needs two or more persons"
        return f"{what}; the facts show {n}"
    return None


def statute_text(era, section, subsection=None):
    """The ingested text of a section -- the sub-section's own text when one is
    named (BNS 3(5) is 194 characters inside a 4,765-character section)."""
    chunk = ranker._section_record(era, section)
    if subsection and subsection != section:
        for _, text, md in store.records(chunk, statute=True):
            if md.get("subsection") == subsection:
                return text
    title = chunk.get("section_title") or ""
    text = chunk["text"]
    return f"{title}. {text}" if title and not text.startswith(title) else text


def _ref(era, v):
    return f"{era.upper()} {v['subsection'] or v['section']}"


def build_messages(state, text_of):
    era = state["era"]
    blocks = []
    for v in state["verified_sections"]:
        t = re.sub(r"\s+", " ", text_of(era, v["section"], v.get("subsection")))[:MAX_STATUTE_CHARS]
        blocks.append(f"[{_ref(era, v)}] {v.get('title') or ''}\n{t}")
    system = (
        "You check whether sections of Indian criminal law apply to a set of facts. For EACH "
        "section listed, read its text, then: copy up to three short passages WORD FOR WORD from "
        "the facts that establish the offence (copy exactly; do not paraphrase); name the "
        "essential ingredient of the section that the facts do not show, or leave it empty if "
        "every ingredient is shown; and say whether the section applies. A section applies only "
        "if the facts show every essential ingredient. Assess every section, in the order given, "
        "using the section reference exactly as written in the brackets.")
    user = f"Facts:\n{state['case_facts']}\n\nSections:\n\n" + "\n\n".join(blocks)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


PASSES = 2


def assess(state, llm, text_of=statute_text, passes=PASSES):
    """Node 2b. Returns {"applicability": [...]}, one record per verified section.

    Self-consistency: the check runs `passes` times, the section order reversed
    on each alternate pass, and a section is supported if ANY pass supports it
    -- i.e. it is demoted only when every pass rejects it. Measured on the dev
    set, 2026-09-27: one pass lost 0 relevant sections on one run and 4 on the
    next, when only the candidate list in the prompt had changed. A verdict that
    flips with prompt order must not be able to remove the right charge.
    """
    verified = state["verified_sections"]
    if not verified:
        return {"applicability": []}
    runs = []
    for p in range(passes):
        order = verified if p % 2 == 0 else list(reversed(verified))
        recs = _assess_once({**state, "verified_sections": order}, llm, text_of)
        by = {(r["section"], r["subsection"]): r for r in recs}
        runs.append([by[(v["section"], v["subsection"])] for v in verified])
    out = []
    for i, v in enumerate(verified):
        recs = [run[i] for run in runs]
        best = next((r for r in recs if r["supported"]), recs[0])
        out.append({**best, "passes": [r["supported"] for r in recs]})
    return {"applicability": out}


def _assess_once(state, llm, text_of):
    era, verified = state["era"], state["verified_sections"]
    reply = llm(build_messages(state, text_of), SCHEMA)
    assessments = reply.get("assessments") or []
    # The model echoes the reference loosely -- "[BNS 303(1)] Theft", measured
    # 2026-09-27 -- so the section number is parsed out of whatever it wrote.
    # If that fails and it returned exactly one assessment per section, the
    # order it was asked to keep is used.
    by_sec = {}
    for a in assessments:
        m = _REF.search(str(a.get("section", "")).upper())
        if m:
            by_sec.setdefault(m.group(1), a)
    positional = len(assessments) == len(verified)
    facts_norm = normalise(state["case_facts"])
    out = []
    for i, v in enumerate(verified):
        a = by_sec.get(v["section"]) or (assessments[i] if positional else None)
        if a is None:
            out.append({"section": v["section"], "subsection": v["subsection"], "supported": False,
                        "assessed": False, "grounded_quotes": [], "dropped_quotes": [],
                        "missing_ingredient": "", "model_applies": None})
            continue
        quotes = [str(q) for q in (a.get("facts_quotes") or [])]
        kept = [q for q in quotes if grounded(q, facts_norm)]
        missing = str(a.get("missing_ingredient") or "").strip()
        if nothing_missing(missing):
            missing = ""
        model_applies = bool(a.get("applies"))
        rule = headcount_rule(era, v["section"], state.get("facts_profile"))
        out.append({"section": v["section"], "subsection": v["subsection"], "assessed": True,
                    "supported": model_applies and bool(kept) and not missing and not rule,
                    "grounded_quotes": kept, "dropped_quotes": [q for q in quotes if q not in kept],
                    "missing_ingredient": missing, "model_applies": model_applies,
                    "rule_rejected": rule})
    return out
