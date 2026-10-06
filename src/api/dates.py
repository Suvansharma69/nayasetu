r"""Find the offence date in a case description typed in plain words.

The web interface lets a lawyer describe a case in one message ("on the night
of 15 August 2024 the accused ..."). The Offence-Date Router is deterministic
and load-bearing (CLAUDE.md Section 2), so the date is never guessed by a
model: this module reads only dates WRITTEN in the text, and the interface
asks the user whenever there is none, or more than one, or only a month.

Indian usage throughout: 05/08/2024 is 5 August, never May 8.
"""
from __future__ import annotations

import re
from datetime import date

_MONTHS = {m: i for i, names in enumerate(
    [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
     ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
     ("oct", "october"), ("nov", "november"), ("dec", "december")], 1) for m in names}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"((?:19|20)\d{2})"

_PATTERNS = [
    # 2024-08-15
    (re.compile(rf"(?<!\d){_YEAR}-(\d{{1,2}})-(\d{{1,2}})(?!\d)"), lambda m: (m[1], m[2], m[3])),
    # 15/08/2024, 15-08-2024, 15.08.2024 (day first)
    (re.compile(rf"(?<![\d.]){_DAY}[/.-](\d{{1,2}})[/.-]{_YEAR}(?!\d)"), lambda m: (m[3], m[2], m[1])),
    # 15 August 2024, 15th of Aug, 2024
    (re.compile(rf"(?<!\d){_DAY}\s+(?:of\s+)?{_MON},?\s+{_YEAR}(?!\d)", re.I),
     lambda m: (m[3], _MONTHS[m[2].lower().rstrip('.')], m[1])),
    # August 15, 2024
    (re.compile(rf"\b{_MON}\s+{_DAY},?\s+{_YEAR}(?!\d)", re.I),
     lambda m: (m[3], _MONTHS[m[1].lower().rstrip('.')], m[2])),
]
# "in August 2024": a month with no day. Not enough for the router near 1 July
# 2024, so it is reported for the interface to ask about, never used.
_MONTH_ONLY = re.compile(rf"\b{_MON},?\s+{_YEAR}(?!\d)", re.I)


def find_dates(text):
    """{"dates": [{"date": "YYYY-MM-DD", "text": matched words}, ...] (distinct, in
    order of appearance), "month_only": [matched words]}."""
    text = text or ""
    found, spans = [], []
    for pat, parts in _PATTERNS:
        for m in pat.finditer(text):
            if any(a < m.end() and m.start() < b for a, b in spans):
                continue
            try:
                y, mo, d = (int(x) for x in parts(m))
                iso = date(y, mo, d).isoformat()
            except (ValueError, KeyError):
                continue
            spans.append((m.start(), m.end()))
            found.append((m.start(), iso, m.group(0)))
    found.sort()
    out, seen = [], set()
    for _, iso, words in found:
        if iso not in seen:
            seen.add(iso)
            out.append({"date": iso, "text": words})
    month_only = [m.group(0) for m in _MONTH_ONLY.finditer(text)
                  if not any(a <= m.start() < b for a, b in spans)]
    return {"dates": out, "month_only": month_only}
