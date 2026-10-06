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

from . import ablation, chargeability, offence_rules
from .router import CODE_NAME

MAX_RETRIES = 2
MAX_PROPOSALS = 8

# Node 1 two-ordering union: OFF (decided 2026-10-01 on the dev set, both runs on
# the same code, only this switch differing). Union vs single call: cases with a
# relevant section 14/15 vs 14/15; wanted sections 22/31 vs 20/31; sections per
# case 5.6 vs 3.8; precision 26% vs 35%. Its two gains were a definition (IPC
# 405, where the charge is 406) and plain theft beside an aggravated theft
# already found (BNS 303 beside 305) -- no missed offence was caught -- for 27
# extra sections and a second LLM call per case. NODE1_UNION = True restores it.
NODE1_UNION = False

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
# The fact-profile fields come BEFORE `sections`: the grammar makes the model
# commit to "is this an offence at all, and how many acted together" before it
# names sections. They drive two deterministic rules in statute_identifier():
# declining non-criminal facts (F) and proposing the joint-liability section (D).
PROFILE_FIELDS = ("discloses_offence", "why", "accused_count", "acted_together", "shared_plan_or_object")
PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "discloses_offence": {"type": "boolean"},
        "why": {"type": "string", "maxLength": 200},
        "accused_count": {"type": "integer", "minimum": 0, "maximum": 99},
        "acted_together": {"type": "boolean"},
        "shared_plan_or_object": {"type": "boolean"},
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
    "required": ["discloses_offence", "why", "accused_count", "acted_together",
                 "shared_plan_or_object", "sections"],
}
# Sections only -- the Phase 4 schema, used when the profile is ablated.
SECTIONS_ONLY_SCHEMA = {"type": "object",
                        "properties": {"sections": PROPOSAL_SCHEMA["properties"]["sections"]},
                        "required": ["sections"]}


def proposal_schema():
    if ablation.off("profile"):
        return SECTIONS_ONLY_SCHEMA
    if ablation.off("injury"):
        return PROPOSAL_SCHEMA
    # The injury fields go after the joint-liability ones and before `sections`,
    # for the same reason: commit to the facts before naming sections.
    props = {k: v for k, v in PROPOSAL_SCHEMA["properties"].items() if k != "sections"}
    props.update(offence_rules.INJURY_SCHEMA)
    props["sections"] = PROPOSAL_SCHEMA["properties"]["sections"]
    return {"type": "object", "properties": props,
            "required": PROPOSAL_SCHEMA["required"][:-1] + list(offence_rules.INJURY_FIELDS) + ["sections"]}


def _code_short(era):
    return era.upper()


def _system_prompt(era):
    code = _code_short(era)
    return (
        f"You assist an Indian criminal lawyer. Identify the sections of the {CODE_NAME[era]} "
        "that the facts disclose. Read the facts as a court reads a complaint at the stage of "
        "registering an FIR or framing a charge: take the allegations as true and ask whether they "
        "disclose an offence prima facie -- do not demand proof, and do not dismiss a threat, "
        "injury or taking of property as a civil matter. "
        f"The offence date decides the code, and for this case it is "
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
        f"{MAX_PROPOSALS - 2}, most important first."
        + ("" if ablation.off("profile") else "\n" + _PROFILE_PROMPT)
        + ("" if ablation.off("profile") or ablation.off("injury") else "\n" + offence_rules.injury_prompt(era))
    )


_PROFILE_PROMPT = (
        "Before the sections, answer about the facts:\n"
        "- discloses_offence: taking every allegation as true, do the facts disclose any criminal "
        "offence? Answer false only for a purely civil, contractual, tax, service or family dispute "
        "in which no criminal act is alleged at all. `why`: one sentence saying why.\n"
        "- accused_count: how many distinct accused persons took part (0 if the facts do not say).\n"
        "- acted_together: true if two or more accused took part in the criminal act jointly.\n"
        "- shared_plan_or_object: true if they shared an intention, plan or object, whether "
        "agreed beforehand or formed on the spot."
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
    reply = llm(build_messages(state), proposal_schema())
    update = {"retry_count": rnd}
    if not is_retry and not ablation.off("profile"):
        profile = {k: reply.get(k) for k in PROFILE_FIELDS + offence_rules.INJURY_FIELDS}
        update["facts_profile"] = profile
        if profile.get("discloses_offence") is False:
            # The model may NOT decline a case. Missing an offence is this
            # system's primary error (owner, 2026-10-01): a bare "no offence"
            # tells the lawyer to stop looking. Measured twice -- a two-man
            # phone snatching (dev 10) and a threat to burn a family's house
            # down (held-out 2 #14) were both called civil disputes. "No
            # offence" is a WARNING; whatever was proposed is verified as usual,
            # and if nothing was, the report surfaces the retrieved sections.
            update["warnings"] = state.get("warnings", []) + [
                "The model considers that these facts may not disclose a criminal offence "
                f"(\"{profile.get('why') or 'no reason given'}\"). Review the sections shown before "
                "relying on that view."]
    items = list(reply.get("sections") or [])[:MAX_PROPOSALS]
    if NODE1_UNION and not is_retry and not ablation.off("union") and len(state["retrieved"]) > 1:
        # Recall-first ensembling (COLIEE 2025's best statute system decided
        # with several LLMs; missing an offence is this system's primary
        # error): ask again with the candidates in REVERSED order and take the
        # union. A small model's proposals shift with what it reads first; two
        # orderings catch each other's misses. Every proposal still goes
        # through Node 2, so the union cannot add an unverified section.
        flipped = {**state, "retrieved": list(reversed(state["retrieved"]))}
        second = llm(build_messages(flipped), proposal_schema())
        items += list(second.get("sections") or [])[:MAX_PROPOSALS]
    proposals, withdrawn, seen = [], [], set()
    for item in items:
        raw = str(item.get("section", "")).strip()
        key = tuple((p["section"], p["subsection"]) for p in parse_citation(raw)) or raw
        if not raw or key in seen:
            continue
        seen.add(key)
        p = {"raw": raw, "reason": str(item.get("reason", "")).strip(), "round": rnd, "source": "llm"}
        (withdrawn if self_negated(p["reason"]) else proposals).append(p)
    if withdrawn:
        update["withdrawn"] = state.get("withdrawn", []) + withdrawn
    if not is_retry and not ablation.off("profile"):
        proposals += liability_rule(state["era"], update["facts_profile"], proposals)
        proposals = add_injury_rule(state["era"], update["facts_profile"], proposals)
    update["candidate_sections"] = state["candidate_sections"] + proposals
    return update


# The joint-liability rule. Phase 2 measured that retrieval cannot surface IPC
# 34 (rank 146 of 672 for a textbook common-intention case) and Phase 4 that
# Node 1 does not propose it either -- so it is derived from the facts the model
# reports, by a rule, and then verified like any other proposal. Five or more
# persons with a common object is an unlawful assembly: IPC 149 / BNS 190, not 34
# (the distinction Phase 2 dev case 8's note is about).
LIABILITY_RULE = {
    "ipc": {"joint": ("IPC 34", "common intention"), "assembly": ("IPC 149", "unlawful assembly, common object")},
    "bns": {"joint": ("BNS 3(5)", "common intention"), "assembly": ("BNS 190", "unlawful assembly, common object")},
}


def liability_rule(era, profile, proposals):
    """Rule-derived liability proposal, or [] (also [] if Node 1 already named it)."""
    n = profile.get("accused_count")
    if (not isinstance(n, int) or n < 2 or not profile.get("acted_together")
            or not profile.get("shared_plan_or_object")):
        return []
    kind = "assembly" if n >= 5 else "joint"
    raw, what = LIABILITY_RULE[era][kind]
    # Compare (section, sub-section), not the section alone: a bare "3" is BNS
    # "General explanations", which Node 2 rejects as non-chargeable, and it
    # must not stand in for 3(5). Dev case 15 lost common intention this way.
    t = parse_citation(raw)[0]
    already = {(p["section"], p["subsection"]) for prop in proposals for p in parse_citation(prop["raw"])}
    if (t["section"], t["subsection"]) in already:
        return []
    return [{"raw": raw, "reason": f"rule: {n} accused acted together with a shared plan or object ({what})",
             "round": 0, "source": "rule"}]


# A proposal whose own reason says the section does not apply. Measured
# 2026-10-06 on the civil deposit demo: having answered discloses_offence=false,
# the model still listed six sections, each reason opening "The facts do not
# disclose ..." -- a list of what it had ruled out, not proposals. Anchored to
# the START of the reason (or to an explicit "not applicable"), so a reason
# that merely contains a negation ("the accused did not return it") is kept.
_SELF_NEGATED = re.compile(
    r"^\W*(?:the\s+|these\s+)?(?:facts?|complaint|allegations?|case|record)\s+(?:do|does|did)\s+not\b"
    r"|^\W*(?:there\s+is\s+)?no\s+(?:evidence|allegation|indication|act|fact)s?\b"
    r"|^\W*(?:this|the)\s+(?:section|offence|provision)\s+(?:is|does)\s+not\b"
    r"|\bnot\s+(?:applicable|attracted|made\s+out)\b", re.I)


def self_negated(reason):
    return bool(_SELF_NEGATED.search(reason or ""))


def add_injury_rule(era, profile, proposals):
    """Add the hurt section the reported injury calls for (offence_rules.injury_rule).

    Node 2 keeps one entry per section, the first it sees. So when the model
    proposed the same section with a different sub-section (BNS 118(1), hurt by
    weapon, for a fracture that is 118(2)), the rule's proposal goes in front of
    it; otherwise it is appended. If the model named the same thing, no-op."""
    rule = offence_rules.injury_rule(era, profile)
    if rule is None:
        return proposals
    t = parse_citation(rule["raw"])[0]
    parsed = [parse_citation(p["raw"]) for p in proposals]
    if any((q["section"], q["subsection"]) == (t["section"], t["subsection"]) for ps in parsed for q in ps):
        return proposals
    for i, ps in enumerate(parsed):
        if any(q["section"] == t["section"] for q in ps):
            return proposals[:i] + [rule] + proposals[i:]
    return proposals + [rule]


# --- Node 2 -------------------------------------------------------------------

def _title(g, code, sec):
    return g.nodes[cg.section_key(code, sec)].get("title") or "untitled"


def _hint(g, era, sec):
    """Counterpart in the era's code via the VERIFIED mapping, if any.

    Both sides are named with their graph titles, and the hint says the
    counterpart is only right if the original guess was the right offence.
    Measured 2026-09-27: without that, a wrong guess ("421" for a theft) was
    faithfully translated into its real counterpart (BNS 320, concealing
    property from creditors), which then verified.
    """
    caveat = " That is only correct if the original section was the right offence for these facts."
    if era == "bns" and cg.verify_section(g, "ipc", sec):
        succ = cg.get_bns_successor(g, sec)
        return (f"IPC {sec} ({_title(g, 'ipc', sec)}) is an IPC section; under the verified mapping "
                f"its BNS counterpart is BNS {succ} ({_title(g, 'bns', succ)})." + caveat if succ else
                f"IPC {sec} ({_title(g, 'ipc', sec)}) is an IPC section with no verified BNS counterpart.")
    if era == "ipc" and cg.verify_section(g, "bns", sec):
        preds = cg.get_ipc_predecessors(g, sec)
        return (f"BNS {sec} ({_title(g, 'bns', sec)}) is a BNS section; under the verified mapping its "
                f"IPC counterpart is " + ", ".join(f"IPC {p} ({_title(g, 'ipc', p)})" for p in preds)
                + "." + caveat if preds else
                f"BNS {sec} ({_title(g, 'bns', sec)}) is a BNS section with no verified IPC counterpart.")
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
            title = _title(g, era, sec)
            role, why = chargeability.classify(era, sec, p["subsection"])
            if ablation.off("chargeability") and role == "non_chargeable":
                role = "unchecked"
            if role == "non_chargeable":
                # Real, but not a charge: a definition, general exception or
                # punishment rule. Rejected like any other unconfirmed citation,
                # so the retry asks for the offence instead.
                bad.append({**entry, "why": f"{code} {sec} ({title}) is {why}, not an offence a "
                                            "person can be charged under"})
            else:
                pun = None if ablation.off("punish") else (chargeability.punished_by(era, sec)
                                                           or chargeability.definition_punished_by(era, sec))
                if pun and cg.verify_section(g, era, pun):
                    # An IPC charge is framed under the punishing section: the
                    # definition (405) becomes its punishment (406), which keeps
                    # the definition as `defined_in` for the applicability check.
                    # Held-out 3 #8 charged 405 for a 406 case.
                    ok.append({**entry, "section": pun, "subsection": None, "code": era,
                               "title": _title(g, era, pun), "role": role, "defined_in": sec})
                else:
                    if (p["subsection"] and role != "liability" and proposal.get("source") != "rule"
                            and not ablation.off("subsection")):
                        # The model's sub-section is cited as the whole section. Measured
                        # on the demo cases, 2026-10-06: attempt to murder came back as
                        # BNS 109(2) (attempt by a life convict), cheating as 318(1) and
                        # personation as 319(1) (the definitions), and IPC 324, which
                        # has no sub-sections, as 324(1). The section is verified; the
                        # sub-section never was. Rule-chosen sub-sections (118(2),
                        # 3(5)) are kept: a rule picked them from the statute's text.
                        entry = {**entry, "subsection": None, "proposed_subsection": p["subsection"]}
                    ok.append({**entry, "code": era, "title": title, "role": role})
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
