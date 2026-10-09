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
import re
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
# Definitions whose punishing section has a different title. Each pair read from
# the ingested titles. Added 2026-10-07 after Phase 6 external runs charged 299
# beside 302 for one death: 299 -> 304 ('Punishment for culpable homicide not
# amounting to murder'), BNS 100 -> 105 likewise; 443/445 -> 453 and 444/446 ->
# 456 (the house-trespass/house-breaking definitions' basic punishments - the
# purpose-aggravated forms 454/455/457/458 are separate offences Node 1 proposes
# on its own).
DEFINITION_PUNISHED_BY = {
    "ipc": {"319": "323", "320": "325", "349": "352", "350": "352", "351": "352", "464": "465",
            "141": "143", "159": "160", "360": "363", "361": "363", "410": "411",
            "299": "304", "443": "453", "445": "453", "444": "456", "446": "456"},
    "bns": {"114": "115", "116": "117", "128": "131", "129": "131", "130": "131", "101": "103",
            "330": "331", "335": "336", "63": "64", "86": "85", "100": "105"},
}

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
    # The IPC defines an offence in one section and punishes it in another
    # (405 / 406), and a charge is framed under the PUNISHING section. Pairs are
    # read off the titles: "Punishment for X" punishes the section titled "X",
    # exact match only -- "Punishment for culpable homicide not amounting to
    # murder" (304) must NOT attach to 299, which also covers murder. The BNS
    # puts definition and punishment in one section, so it has no pairs.
    out["punished_by"] = {"ipc": {}, "bns": {}}
    norm = lambda t: re.sub(r"[^a-z ]", "", (t or "").lower()).strip()  # noqa: E731
    titled = {}
    for sec, e in out["ipc"].items():
        titled.setdefault(norm(e["title"]), []).append(sec)
    for sec, e in out["ipc"].items():
        m = re.match(r"punishment for (.*)", norm(e["title"]))
        defs = titled.get(m.group(1), []) if m else []
        if len(defs) == 1 and out["ipc"][defs[0]]["class"] == "offence":
            out["punished_by"]["ipc"][defs[0]] = sec
    print("ipc definition -> punishment pairs:", len(out["punished_by"]["ipc"]))
    # Definitions the title rule cannot pair (2026-10-06): "Hurt" is punished by
    # "Punishment for voluntarily causing hurt", "Assault" by "Punishment for
    # assault or criminal force otherwise than...", and the BNS splits a few
    # (114 Hurt / 115). Charged bare, they reached the demo's output (IPC 319,
    # 464). Each pair was checked against the ingested title and text of the
    # punishing section, by Claude, not a lawyer. Culpable homicide (IPC 299 /
    # BNS 100) is left out for the reason above. Read by Node 2 only: retrieval
    # pooling and scoring keep using `punished_by`.
    out["definition_punished_by"] = DEFINITION_PUNISHED_BY
    for code, m in DEFINITION_PUNISHED_BY.items():
        for d, p in m.items():
            if out[code][d]["class"] != "offence" or out[code][p]["class"] != "offence" or d in out["punished_by"][code]:
                sys.exit(f"{code} {d} -> {p}: not an unpaired offence-chapter definition and an offence")
    for code, rules in SUBSECTION_LIABILITY.items():
        for sec in rules:
            if out[code][sec]["class"] != "non_chargeable":
                sys.exit(f"{code} {sec}: sub-section rule on a section not in a non-offence chapter")
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
