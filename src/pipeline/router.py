r"""Stage 0: the Offence-Date Router. Deterministic, no LLM, not a graph node.

CLAUDE.md Section 2: an offence committed before 1 July 2024 is governed by the
IPC, one committed on or after it by the BNS. Every downstream step -- which
statute collection is searched, which code Node 2 verifies against, which
judgments vote -- takes the era this function returns, so it is the one place
the transition date is interpreted.

It is the date of the OFFENCE that decides, never the date of the FIR, charge
sheet or judgment: BNS s358 saves proceedings for offences committed earlier.
"""
from __future__ import annotations

import os
from datetime import date, datetime

DEFAULT_TRANSITION = "2024-07-01"


def transition_date():
    return date.fromisoformat(os.environ.get("BNS_TRANSITION_DATE", DEFAULT_TRANSITION).strip())


def parse_date(offence_date):
    """ISO 'YYYY-MM-DD' string, date or datetime -> date. Anything else raises.

    Deliberately strict: '08/09/2024' is 8 September in India and 9 August in
    the US, and a guessed date is a guessed code.
    """
    if isinstance(offence_date, datetime):
        return offence_date.date()
    if isinstance(offence_date, date):
        return offence_date
    if not isinstance(offence_date, str) or not offence_date.strip():
        raise ValueError(f"offence_date must be an ISO date (YYYY-MM-DD), got {offence_date!r}")
    try:
        return date.fromisoformat(offence_date.strip())
    except ValueError:
        raise ValueError(f"offence_date must be an ISO date (YYYY-MM-DD), got {offence_date!r}") from None


def route(offence_date, today=None):
    """'ipc' for an offence before the transition date, 'bns' on or after it."""
    d = parse_date(offence_date)
    if d > (today or date.today()):
        raise ValueError(f"offence_date {d.isoformat()} is in the future")
    return "ipc" if d < transition_date() else "bns"


def route_period(date_from, date_to, today=None):
    """Eras a course of conduct from `date_from` to `date_to` falls under.

    One era when the whole period is on one side of the transition; ["ipc",
    "bns"] when it straddles it -- e.g. cruelty from January to September 2024,
    where acts before 1 July are IPC 498A and later acts BNS 85. A single-date
    route() would silently charge the whole period under one code.
    """
    a, b = route(date_from, today=today), route(date_to, today=today)
    if parse_date(date_from) > parse_date(date_to):
        raise ValueError(f"offence period runs backwards: {date_from} to {date_to}")
    return [a] if a == b else ["ipc", "bns"]


STRADDLE_WARNING = ("The offence period straddles the IPC-to-BNS transition on 1 July 2024: acts "
                    "before that date fall under the IPC and acts on or after it under the BNS. "
                    "Both are shown; check which acts fall on which side.")

CODE_NAME = {"ipc": "Indian Penal Code, 1860 (IPC)", "bns": "Bharatiya Nyaya Sanhita, 2023 (BNS)"}
