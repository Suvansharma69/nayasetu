r"""Classify every ingested IPC and BNS section: can a person be CHARGED under it?

Why this exists
---------------
Node 2 verifies that a section EXISTS in the routed code. Existence is not
applicability: at Phase 4, "IPC 25" (the definition of "fraudulently") and
"BNS 2" (Definitions) reached verified_sections as though they were charges,
and BNS 2 reached the retrieval top 3 through precedent votes. A definition, a
general exception or a rule about fines is never a charge.

The classification comes from the codes' OWN structure -- the chapter each
section sits in, as ingested from the civictech IPC and the gazette BNS --
plus a short explicit list, never from memory of what a section says:

    offence         the offence chapters (IPC ch. 6-22, BNS ch. V-XX)
    liability       rules that extend liability to a person who did not do
                    every act: common intention, abetment, conspiracy,
                    unlawful-assembly membership, attempt. Charged WITH an
                    offence ("302 read with 34"), so they are proposable.
    non_chargeable  preliminary, definitions and general explanations,
                    punishments in general, general exceptions

BNS 3 is split by sub-section: 3(5) is common intention (IPC 34's text) and is
liability; the rest of BNS 3 is interpretive, like IPC 35-38.

Output: data/mappings/chargeability.json. Run after any statute rebuild:
    venv\Scripts\python.exe scripts\build_chargeability.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
OUT = ROOT / "data" / "mappings" / "chargeability.json"

# Chapters that contain no offences (as ingested: IPC chapters are numbers,
# BNS chapters roman numerals).
NON_OFFENCE_CHAPTERS = {"ipc": {"1", "2", "3", "4"}, "bns": {"I", "II", "III"}}
# Whole chapters of liability-extending rules.
LIABILITY_CHAPTERS = {
    "ipc": {"5", "23"},      # abetment + criminal conspiracy (ch. 5); attempts (ch. 23, s511)
    "bns": {"IV"},           # abetment, criminal conspiracy and attempt (s45-62)
}
# Individual liability rules that sit inside other chapters.
LIABILITY_SECTIONS = {
    "ipc": {"34": "common intention",
            "149": "every member of an unlawful assembly guilty of the offence committed in prosecution of its common object"},
    "bns": {"190": "every member of an unlawful assembly guilty of the offence committed in prosecution of its common object"},
}
# Sub-section rules: section -> {liability sub-sections}; any other citation of
# the section (including the bare number) is non-chargeable.
SUBSECTION_LIABILITY = {"bns": {"3": {"3(5)": "common intention"}}}

KIND = {"ipc": {"1": "a preliminary provision", "2": "a definition or general explanation",
                "3": "a general rule about punishments", "4": "a general exception"},
        "bns": {"I": "a preliminary provision or definition", "II": "a general rule about punishments",
                "III": "a general exception"}}


def main():
    out = {"_README": [
        "Built by scripts/build_chargeability.py from the ingested chapter structure; do not edit by hand.",
        "offence = chargeable; liability = extends liability, charged together with an offence;",
        "non_chargeable = definitions, general explanations, punishment rules, general exceptions.",
        "subsection_liability: for these sections only the listed sub-sections are liability rules;",
        "any other citation of the section, including the bare number, is non_chargeable."],
        "ipc": {}, "bns": {}, "subsection_liability": SUBSECTION_LIABILITY}
    for code, fname in (("ipc", "statutes_ipc.jsonl"), ("bns", "statutes_bns.jsonl")):
        counts = Counter()
        for line in (PROCESSED / fname).read_text(encoding="utf-8").splitlines():
            c = json.loads(line)
            sec, ch = c["section"], str(c.get("chapter"))
            if sec in LIABILITY_SECTIONS[code]:
                cls, why = "liability", LIABILITY_SECTIONS[code][sec]
            elif ch in LIABILITY_CHAPTERS[code]:
                cls, why = "liability", (c.get("chapter_title") or "").strip().lower()
            elif ch in NON_OFFENCE_CHAPTERS[code]:
                cls, why = "non_chargeable", KIND[code][ch]
            else:
                cls, why = "offence", None
            out[code][sec] = {"class": cls, "why": why, "title": c.get("section_title"), "chapter": ch}
            counts[cls] += 1
        print(code, dict(counts))
    for code, rules in SUBSECTION_LIABILITY.items():
        for sec in rules:
            if out[code][sec]["class"] != "non_chargeable":
                sys.exit(f"{code} {sec}: sub-section rule on a section not in a non-offence chapter")
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
