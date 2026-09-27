"""Node 2 is the guarantee: nothing reaches verified_sections unless it is an
ingested section of the ROUTED code. These pin that, plus the citation parser."""
import pytest

from src.pipeline import nodes


@pytest.mark.parametrize("raw, want", [
    ("303", [("303", None, None)]),
    ("Section 303(2)", [("303", "303(2)", None)]),
    ("303 (2) BNS", [("303", "303(2)", "bns")]),
    ("BNS 3(5)", [("3", "3(5)", "bns")]),
    ("u/s 34 IPC", [("34", None, "ipc")]),
    ("S. 379 I.P.C.", [("379", None, "ipc")]),
    ("498-A", [("498A", None, None)]),
    ("498a IPC", [("498A", None, "ipc")]),
    ("120 B", [("120B", None, None)]),
    ("302/34", [("302", None, None), ("34", None, None)]),
    ("Section 379 read with 34", [("379", None, None), ("34", None, None)]),
    ("Section 303 of the Bharatiya Nyaya Sanhita, 2023", [("303", None, "bns")]),
    ("Section 420 of the Indian Penal Code, 1860", [("420", None, "ipc")]),
    ("Section 378 CrPC", [("378", None, "other")]),
    ("Section 173 BNSS", [("173", None, "other")]),
    ("Section 25 of the Arms Act", [("25", None, "other")]),
    ("theft", []),
])
def test_parse_citation(raw, want):
    got = [(p["section"], p["subsection"], p["code_named"]) for p in nodes.parse_citation(raw)]
    assert got == want


def _prop(raw, rnd=0):
    return {"raw": raw, "reason": "r", "round": rnd}


def test_real_era_section_verifies_with_graph_title(g):
    ok, bad = nodes.check(g, "bns", _prop("303(2)"))
    assert not bad and ok[0]["section"] == "303" and ok[0]["subsection"] == "303(2)"
    assert ok[0]["title"] == "Theft" and ok[0]["code"] == "bns"


def test_fabricated_section_is_unconfirmed(g):
    ok, bad = nodes.check(g, "bns", _prop("379A"))
    assert not ok and "not a section of the ingested BNS" in bad[0]["why"]


def test_ipc_number_in_bns_era_is_caught_with_mapped_hint(g):
    ok, bad = nodes.check(g, "bns", _prop("Section 420"))
    assert not ok
    why = bad[0]["why"]
    assert "IPC 420 (Cheating and dishonestly inducing delivery of property) is an IPC section" in why
    assert "BNS 318 (Cheating)" in why and "only correct if the original section" in why


def test_named_wrong_code_is_never_reread_as_era_code(g):
    # BNS 302 is real -- but "IPC 302" means murder, so it must NOT verify as BNS 302.
    ok, bad = nodes.check(g, "bns", _prop("IPC 302"))
    assert not ok and "cites the IPC" in bad[0]["why"] and "BNS 103" in bad[0]["why"]


def test_bns_number_in_ipc_era_gets_predecessor_hint(g):
    ok, bad = nodes.check(g, "ipc", _prop("303"))
    assert not ok and "IPC counterpart is IPC 378 (Theft), IPC 379 (Punishment for theft)" in bad[0]["why"]


def test_other_enactment_is_unconfirmed(g):
    ok, bad = nodes.check(g, "ipc", _prop("Section 378 Cr.P.C."))
    assert not ok and "another enactment" in bad[0]["why"]


def test_unparseable_proposal_is_unconfirmed(g):
    ok, bad = nodes.check(g, "ipc", _prop("theft"))
    assert not ok and bad[0]["why"] == "not a section number"


def test_compound_proposal_verifies_each_part(g):
    ok, bad = nodes.check(g, "ipc", _prop("323/34"))
    assert [v["section"] for v in ok] == ["323", "34"] and not bad


def _state(era, **kw):
    s = {"case_facts": "f", "offence_date": "2024-08-15", "candidate_sections": [],
         "verified_sections": [], "precedents": [], "analytics": {}, "defenses": [],
         "retry_count": 0, "era": era, "retrieved": [], "unconfirmed": []}
    s.update(kw)
    return s


def test_verifier_only_checks_the_current_round(g):
    st = _state("bns", retry_count=1, candidate_sections=[_prop("999", 0), _prop("318", 1)],
                unconfirmed=[{**_prop("999", 0), "why": "x"}])
    upd = nodes.verifier(st, g)
    assert [v["section"] for v in upd["verified_sections"]] == ["318"]
    assert len(upd["unconfirmed"]) == 1          # round 0's rejection not re-added


def test_retry_prompt_quotes_the_unconfirmed_section_and_reason(g):
    st = _state("bns", candidate_sections=[_prop("420")],
                unconfirmed=[{**_prop("420"), "why": "IPC 420 is an IPC section; ... BNS 318."}],
                verified_sections=[{"section": "303", "subsection": None}])
    msgs = nodes.build_messages(st)
    assert '"420": IPC 420 is an IPC section' in msgs[-1]["content"]
    assert "Already verified and kept: BNS 303" in msgs[-1]["content"]


def test_first_round_prompt_has_no_feedback(g):
    msgs = nodes.build_messages(_state("ipc"))
    assert len(msgs) == 2 and "IPC section numbers ONLY" in msgs[0]["content"]


def test_retry_replays_previous_answer_and_bans_rejected_numbers(g):
    st = _state("bns", candidate_sections=[_prop("421"), _prop("303")],
                unconfirmed=[{**_prop("421"), "why": "x"}],
                verified_sections=[{"section": "303", "subsection": None}])
    msgs = nodes.build_messages(st)
    assert msgs[-2]["role"] == "assistant" and '"421"' in msgs[-2]["content"]
    assert "Never propose any of these again: 421" in msgs[-1]["content"]


def test_nonexistent_section_reason_states_the_codes_span(g):
    ok, bad = nodes.check(g, "bns", _prop("421"))
    assert "(sections 3 to 318)" in bad[0]["why"]      # span of the synthetic BNS


@pytest.mark.parametrize("era, raw, why", [
    ("ipc", "25", "definition or general explanation"),     # "fraudulently", proposed at Phase 4
    ("ipc", "76", "general exception"),
    ("bns", "2", "preliminary provision or definition"),    # BNS 2 reached the top 3 by votes
    ("bns", "3", "cite that sub-section"),                  # bare BNS 3 is not common intention
])
def test_non_chargeable_sections_are_rejected_with_reason(g2, era, raw, why):
    ok, bad = nodes.check(g2, era, _prop(raw))
    assert not ok and why in bad[0]["why"] and "not an offence a person can be charged under" in bad[0]["why"]


@pytest.mark.parametrize("era, raw, role", [
    ("ipc", "34", "liability"), ("ipc", "120B", "liability"), ("ipc", "511", "liability"),
    ("ipc", "302", "offence"), ("bns", "3(5)", "liability"), ("bns", "61(2)", "liability"),
    ("bns", "103", "offence"),
])
def test_chargeable_sections_verify_with_role(g2, era, raw, role):
    ok, bad = nodes.check(g2, era, _prop(raw))
    assert not bad and ok[0]["role"] == role
