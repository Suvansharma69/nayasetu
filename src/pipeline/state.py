r"""The LangGraph shared state.

The first eight fields are CLAUDE.md Section 3's schema, with its exact names.
The last three are additions (decided at the Phase 4 plan, 2026-09-27) -- none
of the eight is renamed or repurposed:

    era          "ipc" | "bns", from the router; the ONLY code Node 2 verifies against
    retrieved    the ranked statute candidates Node 1 reads as context
    unconfirmed  proposals Node 2 rejected, each with the reason. The retry prompt
                 must quote the specific unconfirmed section (Section 8), and the
                 Phase 7 report must show unconfirmed citations distinctly, so
                 they have to survive in state rather than be dropped.

Added in the hardening pass (2026-09-27), same rule -- additive only:

    facts_profile  Node 1's answers about the facts (discloses_offence, why,
                   accused_count, acted_together, shared_plan_or_object)
    applicability  Node 2b's grounded check of each verified section
    warnings       things the report must tell the lawyer (e.g. a period that
                   straddles the IPC->BNS transition)

Added for Phase 5 (2026-10-04):

    precedent_pool the judgment chunks nearest the facts, fetched BEFORE generation
                   while the embedder still holds the card; Node 3 filters it

Added 2026-10-06:

    withdrawn      sections Node 1 listed with a reason saying they do NOT apply
                   ("The facts do not disclose ..."); never verified or charged,
                   kept so the report can show what the model ruled out

Entries of candidate_sections / verified_sections / unconfirmed are dicts:
    {"raw", "section", "subsection", "code_named", "reason", "round"}
plus "title" on verified entries and "why" (the rejection reason) on unconfirmed.
"""
from __future__ import annotations

from typing import TypedDict

SECTION3_FIELDS = ("case_facts", "offence_date", "candidate_sections", "verified_sections",
                   "precedents", "analytics", "defenses", "retry_count")


class PipelineState(TypedDict):
    case_facts: str
    offence_date: str
    candidate_sections: list
    verified_sections: list
    precedents: list
    analytics: dict
    defenses: list
    retry_count: int
    era: str
    retrieved: list
    unconfirmed: list
    facts_profile: dict
    applicability: list
    warnings: list
    precedent_pool: dict
    withdrawn: list


def initial_state(case_facts, offence_date, era, retrieved):
    return PipelineState(
        case_facts=case_facts, offence_date=str(offence_date), candidate_sections=[],
        verified_sections=[], precedents=[], analytics={}, defenses=[], retry_count=0,
        era=era, retrieved=list(retrieved), unconfirmed=[], facts_profile={}, applicability=[],
        warnings=[], precedent_pool={}, withdrawn=[],
    )
