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
    intake         a pasted court order/FIR is NOT reduced to its alleged facts first
    pair           retrieval does NOT pool an IPC definition's ranks with its punishing
                   section's (503 found by text, 506 by votes; see ranker.pool_pairs)
    lesser         a plain offence is NOT shown as included in a supported aggravated
                   one (417 beside 420); see offence_rules.py
    injury         Node 1 is NOT asked the injury grade, so no hurt section is derived
                   from it and murder/homicide get no "requires a death" rule doubt
    prima_facie    Node 2b is NOT told to read facts as a court framing a charge
                   (inferences from conduct allowed)
    subsection     Node 2 keeps the model's own sub-section (109(2)) instead of citing
                   the verified section; rule-chosen sub-sections are kept either way

Used by the dev-set diagnosis of 2026-09-29, after the held-out broad-coverage
set showed the hardening pass had not generalised. Never set in production.
"""
from __future__ import annotations

import os

KNOWN = {"profile", "exclude", "chargeability", "judge", "union", "dual", "punish", "pair", "intake", "lesser",
         "injury", "prima_facie", "subsection", "nofacts"}


def off(name):
    if name not in KNOWN:
        raise ValueError(f"unknown ablation {name!r}; one of {sorted(KNOWN)}")
    raw = os.environ.get("PRAMANA_ABLATE", "")
    names = {n.strip() for n in raw.split(",") if n.strip()}
    unknown = names - KNOWN
    if unknown:
        raise ValueError(f"PRAMANA_ABLATE has unknown names {sorted(unknown)}; one of {sorted(KNOWN)}")
    return name in names
