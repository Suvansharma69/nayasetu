r"""Switches for ablation studies: turn one hardening change off at a time.

PRAMANA_ABLATE is a comma list of changes to switch OFF (default: none):

    profile        Node 1's fact-profile questions (and the decline and joint-
                   liability rules that read them); Node 1 is asked for sections only
    exclude        non-chargeable sections are NOT removed from Node 1's candidates
    chargeability  Node 2 does NOT reject non-chargeable sections
    judge          Node 2b (applicability) does not run; every verified section is a charge
    union          Node 1 is asked once, not twice (original + reversed candidate order)
    dual           Node 1 gets only the fused candidate list, not fused + statute-text
    punish         Node 2 keeps an IPC definition (405) instead of its punishing section (406)

Used by the dev-set diagnosis of 2026-09-29, after the held-out broad-coverage
set showed the hardening pass had not generalised. Never set in production.
"""
from __future__ import annotations

import os

KNOWN = {"profile", "exclude", "chargeability", "judge", "union", "dual", "punish"}


def off(name):
    if name not in KNOWN:
        raise ValueError(f"unknown ablation {name!r}; one of {sorted(KNOWN)}")
    raw = os.environ.get("PRAMANA_ABLATE", "")
    names = {n.strip() for n in raw.split(",") if n.strip()}
    unknown = names - KNOWN
    if unknown:
        raise ValueError(f"PRAMANA_ABLATE has unknown names {sorted(unknown)}; one of {sorted(KNOWN)}")
    return name in names
