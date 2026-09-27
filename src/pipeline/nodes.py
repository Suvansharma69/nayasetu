r"""Node 1 (Statute Identifier) and Node 2 (Verifier), and the retry edge.

Node 1 is the only LLM step in Phase 4. It reads the facts and the retrieved
statute candidates and PROPOSES sections. Nothing it says is trusted.

Node 2 is not an LLM and must never become one. A proposal is verified only if
it parses to a section number AND `citation_graph.verify_section(g, era, s)`
holds -- i.e. it is an ingested section of the code the router chose. Proposals
that fail are kept in `unconfirmed` with the reason, and the retry edge sends
Node 1 back with that exact section and reason, at most twice
(`retry_count < 2`, CLAUDE.md Section 8).

Two failure modes the verifier is built around:

* A real number from the WRONG code. Lawyers say "420" out of habit; in the BNS
  there is no s420. Worse, "IPC 302" in a BNS-era case must not verify as BNS
  302, which is a different offence entirely -- so a code the proposal NAMES is
  honoured, never silently re-read as the era's code.
* A number that exists nowhere. Rejected, with the reason.

When a rejected number is a real section of the other code, the feedback adds
its counterpart under the VERIFIED mapping (graph `maps_to` edges). That is a
graph lookup, so it cannot introduce an unverified citation, and whatever Node
1 proposes next is verified from scratch like everything else.

Known limit, stated rather than hidden: a bare number that is real in the era's
code but means something else there (BNS-era "302" meant as murder) passes --
existence is all a graph lookup can establish. The verified entry carries the
graph's own title so the report shows what the section actually is.
"""
from __future__ import annotations

import json
import re

from src.graph import citation_graph as cg

from .router import CODE_NAME

MAX_RETRIES = 2
MAX_PROPOSALS = 8

# --- parsing a proposed citation ------------------------------------------------

_IPC = re.compile(r"\bI\.?\s?P\.?\s?C\b\.?|Indian\s+Penal\s+Code|Penal\s+Code", re.I)
_BNS = re.compile(r"\bB\.?\s?N\.?\s?S\b(?!\.?\s?S\b)|Nyaya\s+Sanhita", re.I)
# Enactments that reuse penal-code numbers for something else (Known Gotchas:
# CrPC 378 is an appeal, IPC 378 is theft).
_OTHER = re.compile(r"Cr\.?\s?P\.?\s?C|B\.?\s?N\.?\s?S\.?\s?S|Nagarik\s+Suraksha|Criminal\s+Procedure"
                    r"|Evidence\s+Act|Sakshya|\bB\.?\s?S\.?\s?A\b|\bAct\b", re.I)
# "120B", "120-B", "498a" and -- as in src/ingest/sections.py -- the spaced
# "120 B", which is allowed only for ONE capital letter so "302 r/w 34" and
# "379 and 34" never become s302R / s379AND.
_NUM = re.compile(r"(?<![\d.])(\d{1,3})(?:\s?-\s?([A-Za-z]{1,3})|([A-Za-z]{1,3})|\s((?-i:[A-Z]))(?![\w/]))?"
                  r"(?![A-Za-z0-9])(?:\s?\(\s?(\d{1,2}[a-z]?)\s?\))?")
_CODE_WORDS = {"IPC", "BNS", "BNSS", "CRPC", "U", "S", "R", "W"}


def parse_citation(raw):
    """A proposed citation string -> list of {section, subsection, code_named}.

    code_named is "ipc", "bns", "other" (a procedure or evidence statute, or
    any other Act) or None when the proposal names no code. Several sections in
    one string ("302/34", "379 read with 34") give several entries.
    """
    text = str(raw or "")
    if _OTHER.search(text):
        code = "other"
    elif _IPC.search(text) and _BNS.search(text):
        code = "other"          # names both: cannot be attributed to either
    elif _IPC.search(text):
        code = "ipc"
    elif _BNS.search(text):
        code = "bns"
    else:
        code = None
    stripped = _IPC.sub(" ", _BNS.sub(" ", text))
    out, seen = [], set()
    for m in _NUM.finditer(stripped):
        letters = (m.group(2) or m.group(3) or m.group(4) or "").upper()
        if letters in _CODE_WORDS:
            letters = ""
        sec = cg.normalise(m.group(1) + letters)
        if sec is None or sec in seen:
            continue
        seen.add(sec)
        sub = f"{sec}({m.group(5)})" if m.group(5) else None
        out.append({"section": sec, "subsection": sub, "code_named": code})
    return out


# --- Node 1 -------------------------------------------------------------------

# The bounds are load-bearing, not tidiness. Unbounded, qwen3.5:4b listed
# sections until Ollama's 5-minute request limit killed it (~4,000 tokens at
# ~16 tok/s, measured 2026-09-27). Ollama compiles maxItems/maxLength into the
# decoding grammar, so the reply ends by construction.
PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "maxItems": MAX_PROPOSALS - 2,
            "items": {
                "type": "object",
                "properties": {"section": {"type": "string", "maxLength": 40},
                               "reason": {"type": "string", "maxLength": 200}},
                "required": ["section", "reason"],
            },
        }
    },
    "required": ["sections"],
}


def _code_short(era):
    return era.upper()


def _system_prompt(era):
    code = _code_short(era)
    return (
        f"You assist an Indian criminal lawyer. Identify the sections of the {CODE_NAME[era]} "
        f"that the facts disclose. The offence date decides the code, and for this case it is "
        f"the {code}: cite {code} section numbers ONLY, never those of any other enactment.\n"
        "Name only the sections the accused could be CHARGED under: sections whose every "
        "ingredient the facts disclose. Do not name general exceptions, private defence or "
        "procedure, and do not name a section merely because it appears in the candidate list.\n"
        "Candidate sections retrieved from the statute text are listed with the facts. They are "
        "suggestions: most will be irrelevant and some applicable sections may be missing. You may "
        "propose a section that is not listed when the facts call for it, including general "
        "provisions such as joint liability, abetment or attempt.\n"
        "For each section give the bare number (with the sub-section in brackets if one is "
        "specifically engaged, e.g. 303(2)) and a one-sentence reason tied to the facts. "
        "A case usually engages one to three sections; propose at most "
        f"{MAX_PROPOSALS - 2}, most important first. If the facts "
        "disclose no criminal offence (for example a purely civil, contractual or family "
        "dispute), return an empty list."
    )


def _candidates_block(retrieved, era):
    lines = []
    for r in retrieved:
        ref = r.get("matched") or r["section"]
        title = r.get("title") or ""
        excerpt = r.get("excerpt") or ""
        lines.append(f"- {_code_short(era)} {ref}: {title}. {excerpt}".rstrip())
    return "\n".join(lines) or "(none)"


def build_messages(state):
    era = state["era"]
    user = (f"Offence date: {state['offence_date']} (so the {_code_short(era)} applies)\n\n"
            f"Facts:\n{state['case_facts']}\n\n"
            f"Retrieved candidate sections:\n{_candidates_block(state['retrieved'], era)}")
    msgs = [{"role": "system", "content": _system_prompt(era)},
            {"role": "user", "content": user}]
    rejected = _open_rejections(state)
    if rejected:
        # The model's own previous answer goes back as an assistant turn. Measured
        # 2026-09-27: with the feedback as a bare follow-up message, qwen3.5:4b
        # re-proposed the same rejected number ("421") in all three rounds.
        prev = [c for c in state["candidate_sections"] if c["round"] == state["retry_count"]]
        msgs.append({"role": "assistant", "content": json.dumps(
            {"sections": [{"section": c["raw"], "reason": c["reason"]} for c in prev]})})
        kept = ", ".join(f"{_code_short(era)} {v['subsection'] or v['section']}"
                         for v in state["verified_sections"]) or "none"
        fb = "\n".join(f"- \"{u['raw']}\": {u['why']}" for u in rejected)
        banned = sorted({u["raw"] for u in state["unconfirmed"]})
        msgs.append({"role": "user", "content": (
            "Your previous answer cited sections that could not be verified against the "
            f"ingested {_code_short(era)}:\n{fb}\n\n"
            f"Never propose any of these again: {', '.join(banned)}. "
            f"Already verified and kept: {kept}; do not repeat them either. Propose correct "
            f"{_code_short(era)} sections to replace the unverified ones, or an empty list if none "
            "applies.")})
    return msgs


def _open_rejections(state):
    """Rejections from the current round -- what a retry must answer.

    The round number IS retry_count (round 0 is the first call; Node 1 bumps it
    on each retry). Keyed on retry_count rather than on the latest proposal, so
    a retry that proposes nothing ends the loop instead of re-answering the
    previous round's rejections forever.
    """
    return [u for u in state["unconfirmed"] if u["round"] == state["retry_count"]]


def statute_identifier(state, llm):
    """Node 1. Returns the state update: this round's proposals appended to
    candidate_sections (which keeps every round, for Phase 6's catch rate)."""
    # Node 1 is only re-entered through route_after_verify, which requires open
    # rejections -- so their presence is what marks a retry.
    is_retry = bool(_open_rejections(state))
    rnd = state["retry_count"] + 1 if is_retry else 0
    reply = llm(build_messages(state), PROPOSAL_SCHEMA)
    proposals = []
    for item in (reply.get("sections") or [])[:MAX_PROPOSALS]:
        raw = str(item.get("section", "")).strip()
        if not raw:
            continue
        proposals.append({"raw": raw, "reason": str(item.get("reason", "")).strip(), "round": rnd})
    return {"candidate_sections": state["candidate_sections"] + proposals,
            "retry_count": rnd}


# --- Node 2 -------------------------------------------------------------------

def _hint(g, era, sec):
    """Counterpart in the era's code via the VERIFIED mapping, if any."""
    if era == "bns" and cg.verify_section(g, "ipc", sec):
        succ = cg.get_bns_successor(g, sec)
        return (f"IPC {sec} is an IPC section; under the verified mapping its BNS counterpart "
                f"is BNS {succ}." if succ else
                f"IPC {sec} is an IPC section with no verified BNS counterpart.")
    if era == "ipc" and cg.verify_section(g, "bns", sec):
        preds = cg.get_ipc_predecessors(g, sec)
        return (f"BNS {sec} is a BNS section; under the verified mapping its IPC counterpart "
                f"is IPC {', '.join(preds)}." if preds else
                f"BNS {sec} is a BNS section with no verified IPC counterpart.")
    return ""


def _range(g, era):
    """' (sections 1 to 358)' -- the code's real span, read off the graph."""
    key = f"_span_{era}"
    if key not in g.graph:
        nums = [int(re.match(r"\d+", d["section"]).group()) for _, d in g.nodes(data=True)
                if d.get("kind") == "section" and d.get("code") == era]
        g.graph[key] = (min(nums), max(nums)) if nums else None
    span = g.graph[key]
    return f" (sections {span[0]} to {span[1]})" if span else ""


def check(g, era, proposal):
    """Verify one proposal. Returns (verified entries, unconfirmed entries)."""
    code = _code_short(era)
    base = {k: proposal[k] for k in ("raw", "reason", "round")}
    parsed = parse_citation(proposal["raw"])
    if not parsed:
        return [], [{**base, "section": None, "subsection": None, "code_named": None,
                     "why": "not a section number"}]
    ok, bad = [], []
    for p in parsed:
        entry = {**base, **p}
        sec, named = p["section"], p["code_named"]
        if named == "other":
            bad.append({**entry, "why": f"cites another enactment, not the {code}"})
        elif named is not None and named != era:
            bad.append({**entry, "why": (f"cites the {named.upper()}, but the offence date means "
                                         f"only the {code} applies. " + _hint(g, era, sec)).strip()})
        elif not cg.verify_section(g, era, sec):
            bad.append({**entry, "why": (f"{code} {sec} is not a section of the ingested "
                                         f"{code}{_range(g, era)}. " + _hint(g, era, sec)).strip()})
        else:
            title = g.nodes[cg.section_key(era, sec)].get("title")
            ok.append({**entry, "code": era, "title": title})
    return ok, bad


def verifier(state, g):
    """Node 2. Deterministic graph lookup over the latest round's proposals."""
    era = state["era"]
    last = state["retry_count"]
    verified = list(state["verified_sections"])
    have = {v["section"] for v in verified}
    unconfirmed = list(state["unconfirmed"])
    for prop in (c for c in state["candidate_sections"] if c["round"] == last):
        ok, bad = check(g, era, prop)
        for v in ok:
            if v["section"] not in have:
                verified.append(v)
                have.add(v["section"])
        unconfirmed.extend(bad)
    return {"verified_sections": verified, "unconfirmed": unconfirmed}


def route_after_verify(state):
    """Back to Node 1 iff the latest round left something unconfirmed and
    fewer than MAX_RETRIES retries have run."""
    if _open_rejections(state) and state["retry_count"] < MAX_RETRIES:
        return "statute_identifier"
    return "end"
