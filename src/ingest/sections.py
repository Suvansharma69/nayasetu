r"""Pull statutory section references out of judgment text.

This feeds `sections_involved`, which is what Phase 3 builds the case->section
edges of the citation graph from. Everything downstream -- precedent matching,
outcome analytics -- keys on it, so a false positive here becomes a fabricated
edge in the graph that Node 2 would then happily "verify".

Two defences against that:

1. Shape. Only forms a court actually writes are matched: "u/s. 302",
   "u/ss. 302/34", "Section 364", "Sections 302/34", "under section 420".
   A bare number is never a citation.
2. Membership. A candidate survives only if it is a section that really exists
   in the ingested IPC or BNS. This is the CLAUDE.md verification rule applied
   at ingest time, and it is what kills the residue the shape rules let past --
   a naive regex over one real judgment matched "s. 1578" and "s. 6" (a stray
   number and a paragraph reference); neither is a section of anything, so
   neither survives the membership check.

Sub-sections are deliberately flattened: "303(2)" yields "303". The citation
graph keys on the section, and splitting nodes per sub-section would fragment
the precedent counts that Phase 5 aggregates over.
"""
from __future__ import annotations

import re

# One section number as courts write it: "302", "120B", "120-B", and -- in the
# scrubbed High Court text of NyayaAnumana -- "120 B". The spaced form is only
# a single CAPITAL letter standing alone (case-sensitive even though the outer
# pattern is not), so "34 IPC" and "34 r w 149" are never read as "34I"/"34R".
_NUM = r"\d{1,3}(?:\s*-\s*[A-Z]{1,3}|[A-Z]{1,3}|(?-i:\s[A-Z]\b))?"
# "303(2)", "13(1)(d)", "376(2)(i)", "378(1) and (3)", "378 (1) (3)" --
# sub-section and clause, dropped later. The "and (3)" form must be consumed
# here, or the enactment check below reads " and (3) of Code of Criminal
# Procedure" and cannot see what the section belongs to.
_SUB = r"(?:\s*(?:(?:and|&|,|/)\s*)?\(\d+\))*(?:\s*\([a-z]{1,4}\))*"

# "u/s. 302", "u/ss. 302/34 and 364/34", "Section 420", "under sections 34, 149",
# "Section 120 B r w 420". The trailing group is a run of numbers joined by
# / , & "and" "r/w" "read with" -- courts cite compound charges that way and
# each member is a separate section.
_CITATION = re.compile(
    rf"""
    (?:under\s+)?                      # "under section 420"
    (?:u/\s*)?                         # "u/s. 302"
    \bs(?:ec(?:tion)?)?s?\b\.?         # s / ss / sec / secs / section / sections
    \s*
    (?P<body>
        {_NUM}{_SUB}
        (?:\s*(?:/|,|&|and|r\s?/\s?w|r\.?\s+w\.?|read\s+with)\s*{_NUM}{_SUB})*
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# The hyphen in "120-B" is typographic, not structural. Courts write IPC 120B
# both ways and the gazette writes it closed up; a member regex that stops at
# the digits turns a citation to s120B (criminal conspiracy) into one to s120
# (concealing a design), which is a real but entirely unrelated section -- it
# passes the membership check and lands a wrong edge in the citation graph.
# The hyphen is only consumed when letters actually follow, so a numeric range
# like "Sections 302-304" is not mangled into a single bogus section.
_MEMBER = re.compile(_NUM, re.IGNORECASE)

# What the citation is a section OF. Membership alone cannot answer this: the
# CrPC, the Evidence Act and a dozen special Acts reuse the same numbers, and
# the collisions land on exactly the offences this project is about. "Section
# 378 Cr.P.C." (appeal against acquittal) passes an IPC membership check as
# theft; "Section 406 Cr.P.C." (transfer of cases) as criminal breach of
# trust; "Section 482 Cr.P.C." as using a false property mark. Before this
# check, 7,035 such CrPC citations sat in the SC corpus's sections_involved as
# IPC sections -- i.e. as edges in the citation graph, looking verified.
#
# So the words right after a citation are read. A citation that names the
# penal code is kept; one that names any other enactment is dropped whole
# (every member of a compound goes with it); one that names nothing is kept,
# as before, because "Section 302" bare in a criminal judgment is the code.
# Bare "the Code" is treated as another enactment: in criminal judgments it is
# almost always the CrPC, and dropping a real IPC cite costs recall while
# keeping a CrPC one fabricates a graph edge.
# A short parenthetical between the number and the enactment -- "Sections 378
# and 379 (sic 378) CrPC" -- is skipped, so it cannot hide the enactment.
_ASIDE = r"[\s,]*(?:\([^()]{0,24}\)[\s,]*)?"
_PENAL = re.compile(
    _ASIDE + r"(?:of\s+)?(?:the\s+)?(?:Indian\s+Penal\s+Code|Penal\s+Code"
    r"|I\.?\s?P\.?\s?C\b|Bharatiya\s+Nyaya|B\.?\s?N\.?\s?S\b(?!\.?\s?S))",
    re.IGNORECASE,
)
_OTHER_ENACTMENT = re.compile(
    _ASIDE + r"(?:of\s+)?(?:the\s+)?(?:said\s+)?"
    r"(?:(?i:Crl?\.?\s?P\.?\s?C\b|Code\s+of\s+Criminal\s+Procedure"
    r"|Criminal\s+Procedure\s+Code|B\.?\s?N\.?\s?S\.?\s?S\b|Bharatiya\s+(?:Nagarik|Sakshya)"
    r"|N\.?\s?D\.?\s?P\.?\s?S\b|Code\b|Evidence\s+Act)"
    # "of the Act", "of the Arms Act", "of the Protection of Children from
    # Sexual Offences Act, 2012", "of P.C Act" -- an enactment's name must
    # OPEN with a capitalised word, so "Section 379 and the Arms Act" (a real
    # IPC cite followed by prose) is not swallowed as naming the Arms Act.
    r"|(?:[A-Z][\w.()'&-]*\s+"
    r"(?:(?:[A-Z][\w.()'&-]*|of|from|and|for|the|in|to|on)\s+){0,9})?"
    r"(?:Act|Rules?|Regulations?|Ordinance)\b)",
)


def _names_other_enactment(text, end):
    trail = text[end:end + 120]
    if _PENAL.match(trail):
        return False
    return bool(_OTHER_ENACTMENT.match(trail))


def _canonical(raw):
    return re.sub(r"[\s-]", "", raw).upper()

# Which code a judgment is working under. The SCR "List of Acts" block states
# this explicitly ("Penal Code, 1860."), which is far more reliable than
# guessing from the section numbers -- IPC 302 and BNS 302 are both real and
# completely different offences.
_ACT_HINTS = (
    ("ipc", re.compile(r"penal\s+code|\bI\.?P\.?C\.?\b", re.I)),
    ("bns", re.compile(r"bharatiya\s+nyaya\s+sanhita|\bB\.?N\.?S\.?\b", re.I)),
)


def detect_corpus(text):
    """Which code this judgment applies: 'ipc', 'bns', both, or neither."""
    return [name for name, pat in _ACT_HINTS if pat.search(text)]


def extract_sections(text, valid):
    """Section numbers cited in `text` that exist in `valid`.

    `valid` is a set of canonical section strings from the ingested statutes.
    Passing an empty set returns nothing -- deliberately. Callers must supply
    the real corpus; there is no "trust the regex" mode, because an unchecked
    reference is exactly the fabricated citation this project exists to stop.
    """
    found = []
    for m in _CITATION.finditer(text):
        if _names_other_enactment(text, m.end()):
            continue
        for member in _MEMBER.finditer(m.group("body")):
            s = _canonical(member.group(0))
            if s not in valid and " " in member.group(0).strip():
                # "307 A.P." -- a spaced capital that is not a suffix after
                # all. Fall back to the number. Only the SPACED form falls
                # back: "120-B"/"120B" never degrade to "120" (see _MEMBER).
                s = _canonical(re.match(r"\d+", member.group(0)).group(0))
            if s in valid and s not in found:
                found.append(s)
    return found


def statute_section_set(chunks, corpus=None):
    """The set of section numbers present in parsed statute chunks."""
    return {
        c["section"] for c in chunks
        if c["doc_type"] == "statute" and (corpus is None or c["corpus"] == corpus)
    }


def section_index(*chunk_lists):
    """Build {corpus: {sections}} plus a union, for corpus-aware validation.

    Validating a citation against the UNION of IPC and BNS would be a quiet
    error: the two codes renumbered everything, so s302 is murder under the IPC
    and wounding religious feelings under the BNS, and s303 is theft under the
    BNS but was punishment-for-murder-by-a-life-convict under the IPC. A
    judgment's sections must be checked against the code that judgment is
    actually applying, or the citation graph gains edges to the wrong offence
    entirely -- while looking perfectly verified.
    """
    index = {}
    for chunks in chunk_lists:
        for c in chunks:
            if c["doc_type"] == "statute":
                index.setdefault(c["corpus"], set()).add(c["section"])
    index["_union"] = set().union(*index.values()) if index else set()
    return index


def valid_for(index, corpora):
    """Pick the section set to validate against, given detected corpora.

    One detected code -> that code's sections. Ambiguous (a judgment that
    discusses both, common around the transition) or none detected -> the
    union, because narrowing on a guess would drop real citations.
    """
    if len(corpora) == 1 and corpora[0] in index:
        return index[corpora[0]]
    return index["_union"]
