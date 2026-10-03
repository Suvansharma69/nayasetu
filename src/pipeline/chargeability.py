r"""Is a verified section something a person can be charged under?

Reads data/mappings/chargeability.json (built by scripts/build_chargeability.py
from the codes' own chapter structure). Node 2 uses it as a second, stricter
check after existence: a definition or general exception is a real section,
but proposing it as a charge is still wrong. See that script for the classes.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "data" / "mappings" / "chargeability.json"

_data = None


def _load():
    global _data
    if _data is None:
        _data = json.loads(PATH.read_text(encoding="utf-8"))
    return _data


def classify(code, section, subsection=None):
    """(class, why) with class in {"offence", "liability", "non_chargeable", "unknown"}."""
    d = _load()
    entry = d.get(code, {}).get(section)
    if entry is None:
        return "unknown", "not an ingested section"
    subs = d.get("subsection_liability", {}).get(code, {}).get(section)
    if subs:
        if subsection in subs:
            return "liability", subs[subsection]
        named = ", ".join(f"{code.upper()} {s} ({w})" for s, w in subs.items())
        return "non_chargeable", (f"{code.upper()} {section} is {entry['why']}; only {named} "
                                  "extends liability -- cite that sub-section")
    return entry["class"], entry["why"]


def chargeable(code, section, subsection=None):
    return classify(code, section, subsection)[0] in ("offence", "liability")


def punished_by(code, section):
    """The section that punishes this definition (IPC 405 -> 406), or None."""
    return _load().get("punished_by", {}).get(code, {}).get(section)


def non_chargeable_sections(code):
    """Sections that can never be a charge at section level (for filtering
    retrieval candidates and precedent votes). Sections with a sub-section
    rule (BNS 3) are NOT included: their liability sub-section is proposable."""
    d = _load()
    special = set(d.get("subsection_liability", {}).get(code, {}))
    return {s for s, e in d[code].items() if e["class"] == "non_chargeable" and s not in special}
