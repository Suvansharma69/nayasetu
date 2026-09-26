r"""Propose IPC <-> BNS section correspondences from the ingested text.

CLAUDE.md calls the mapping table the highest-risk task in Phase 1 and says
explicitly: spot-check against real gazette text, DO NOT fully automate. This
script therefore does not produce a mapping. It produces CANDIDATES, each with
the evidence behind it, which a human then confirms or rejects. Every row lands
with "verified": false and only a person may flip it.

Why similarity works here at all
--------------------------------
The BNS re-enacted most of the IPC with the wording substantially preserved and
the numbering completely changed -- IPC 378 (theft) became BNS 303, IPC 420
(cheating) became BNS 318. So the text is a genuine signal while the number is
actively misleading: IPC 302 is murder, BNS 302 is uttering words to wound
religious feelings. A number-based mapping would be wrong almost everywhere.

Both sides come from data we ingested and verified ourselves, so a proposal can
never reference a section that does not exist.

Why the score is not the answer
-------------------------------
Similarity cannot see a change in legal substance. The BNS altered ingredients,
punishments and thresholds in places while keeping the prose nearly identical,
and it introduced offences with no IPC predecessor at all (BNS 304, snatching).
A high score means "same words", not "same offence" -- which is exactly why a
person has to sign the row off.

Run:  venv\Scripts\python.exe scripts\build_mapping.py
"""
import json
import re
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ingest.statutes import parse_bns, parse_ipc

OUT = ROOT / "data" / "mappings" / "ipc_bns_candidates.json"

# Offence types Phase 1 curates for (CLAUDE.md Section 4 rule 2). These get
# looked at first because they are what the Phase 2 test cases exercise.
IN_SCOPE = re.compile(
    r"theft|assault|hurt|cheat|common intention|criminal conspiracy|"
    r"robbery|dacoity|extortion|snatch|misappropriat|breach of trust|"
    r"criminal intimidation|murder|culpable homicide",
    re.I,
)

_STOP = re.compile(r"\b(whoever|shall|be|punished|with|imprisonment|of|either|"
                   r"description|for|a|term|which|may|extend|to|or|fine|both|"
                   r"and|the|any|is|said|in|that|he|his|it|as|by|such|person)\b",
                   re.I)


def signature(text):
    """The set of content words, so boilerplate punishment prose stops dominating.

    Nearly every penal section ends "shall be punished with imprisonment of
    either description for a term which may extend to...". Left in, that
    phrasing alone scores two unrelated offences as highly similar.
    """
    return frozenset(re.findall(r"[a-z]{4,}", _STOP.sub(" ", text.lower())))


def score(a, b):
    """Overlap coefficient: how much of the SMALLER section the larger contains.

    Two earlier attempts were wrong, both in instructive ways.

    Sorting the content words into a string and running SequenceMatcher over it
    compared character runs rather than words: IPC 378 (theft) matched BNS 97
    (selling a child for prostitution) at 0.52, while BNS 303 -- the section the
    CLAUDE.md worked example turns on, and whose wording is near-identical --
    did not win.

    Plain Jaccard then scored that same true pair at 0.056, because the two
    corpora are shaped differently: the IPC records are the bare provision (13
    content words for s378) while the gazette's BNS sections carry all their
    Explanations and Illustrations inline (233 for s303). Jaccard divides by the
    union, so a 20x size gap caps the score near zero however well the text
    matches. The BNS also merged provisions the IPC split -- IPC 378 defines
    theft and 379 punishes it; BNS 303 does both -- so the size gap is
    structural, not incidental.

    Containment is the relationship that actually holds: the old provision
    should appear inside the new one. It separates the real pairs cleanly
    (theft 1.00, cheating 0.96, murder 0.86) from the false ones the earlier
    scorers picked (IPC 378 vs BNS 97: 0.31).
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


# Below this many content words, containment is meaningless: a three-word
# section is "wholly contained" in half the Sanhita by coincidence. Such rows
# are still emitted -- dropping a section silently is worse -- but flagged so a
# reviewer treats the score as noise rather than evidence.
MIN_TERMS_FOR_CONFIDENCE = 8


def main():
    ipc, _ = parse_ipc()
    bns = parse_bns()
    print(f"IPC {len(ipc)} sections, BNS {len(bns)} sections")

    bns_sig = [(c, signature(c["text"])) for c in bns]

    rows = []
    for c in ipc:
        sig = signature(c["text"])
        ranked = sorted(
            ((score(sig, bsig), b) for b, bsig in bns_sig),
            key=lambda t: -t[0],
        )[:3]
        best, top = ranked[0][1], ranked[0][0]
        rows.append({
            "ipc_section": c["section"],
            "ipc_title": c["section_title"],
            "bns_section": best["section"],
            "bns_title": best["section_title"],
            "similarity": round(top, 3),
            # The runner-up matters: a candidate that beats its rival by a hair
            # is a coin toss dressed up as a number, and is the first thing a
            # reviewer should look at.
            "runner_up": {
                "bns_section": ranked[1][1]["section"],
                "bns_title": ranked[1][1]["section_title"],
                "similarity": round(ranked[1][0], 3),
            } if len(ranked) > 1 else None,
            "in_scope": bool(IN_SCOPE.search(c["section_title"] or "")),
            # How much evidence the score rests on. A handful of content words
            # makes a 1.00 meaningless; the reviewer needs to see that.
            "ipc_terms": len(sig),
            "low_evidence": len(sig) < MIN_TERMS_FOR_CONFIDENCE,
            "verified": False,
            "verified_by": None,
            "note": "",
        })

    rows.sort(key=lambda r: (not r["in_scope"], -r["similarity"]))
    payload = {
        "_README": [
            "CANDIDATE IPC<->BNS correspondences, machine-proposed, NOT a mapping.",
            "Nothing here is usable until 'verified' is true, set by a person who",
            "checked the row against the real gazette text of both sections.",
            "Similarity is over content words only and measures WORDING, not legal",
            "substance: the BNS changed ingredients and punishments in places while",
            "keeping the prose, and added offences with no IPC predecessor at all.",
            "A low 'similarity' or a close 'runner_up' means look harder, not skip.",
        ],
        "generated_from": {
            "ipc": "civictech-India/Indian-Law-Penal-Code-Json (ingested)",
            "bns": "MHA gazette PDF No. 45 of 2023 (ingested)",
        },
        "counts": {
            "rows": len(rows),
            "in_scope": sum(r["in_scope"] for r in rows),
            "verified": 0,
        },
        "rows": rows,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"-> {OUT}  ({len(rows)} candidates, "
          f"{payload['counts']['in_scope']} in scope, 0 verified)")

    print("\ntop in-scope candidates for review:")
    for r in [r for r in rows if r["in_scope"]][:15]:
        print(f"  IPC {r['ipc_section']:5} {str(r['ipc_title'])[:34]:36}"
              f" -> BNS {r['bns_section']:4} {str(r['bns_title'])[:30]:32}"
              f" {r['similarity']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
