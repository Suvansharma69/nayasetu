"""The LangGraph loop end to end, with a scripted LLM and injected retrieval.

These are the mechanics behind the Phase 4 gate: the retry edge fires on an
unconfirmed section, feeds it back, caps at retry_count < 2, and never lets an
unconfirmed section into verified_sections."""
import re

from src.pipeline import graph
from src.pipeline.state import SECTION3_FIELDS

FACTS = "The accused took the complainant's motorcycle without consent and rode away."
RETRIEVED = [{"section": "303", "title": "Theft", "matched": "303(2)", "excerpt": "Whoever ..."}]


def _run(g, llm, date="2024-08-15", sufficient=True, check_applicability=True):
    return graph.run(FACTS, date, llm=llm, g=g, retrieve=lambda f, era: RETRIEVED,
                     sufficient=lambda f, era: (sufficient, {"top_similarity": 0.5}),
                     text_of=lambda era, sec, sub: f"statute text of {era} {sub or sec}",
                     check_applicability=check_applicability)


def test_clean_first_answer_needs_no_retry(g, scripted):
    llm = scripted(["303(2)"])
    out = _run(g, llm)
    st = out["state"]
    assert out["status"] == "ok" and len(llm.calls) == 1 and st["retry_count"] == 0
    assert [v["section"] for v in st["verified_sections"]] == ["303"] and st["unconfirmed"] == []


def test_fabricated_then_corrected_on_first_retry(g, scripted):
    llm = scripted(["303", "420"], ["318"])
    st = _run(g, llm)["state"]
    assert len(llm.calls) == 2 and st["retry_count"] == 1
    # verified in round 0 survives the retry; the replacement joins it
    assert [v["section"] for v in st["verified_sections"]] == ["303", "318"]
    assert [u["raw"] for u in st["unconfirmed"]] == ["420"]
    # the retry prompt named the specific section and the mapped counterpart
    assert '"420"' in llm.calls[1][-1]["content"] and "BNS 318" in llm.calls[1][-1]["content"]


def test_retry_cap_stops_after_two_retries(g, scripted):
    llm = scripted(["379A"])                     # fabricates every time
    out = _run(g, llm)
    st = out["state"]
    assert len(llm.calls) == 3 and st["retry_count"] == 2
    assert st["verified_sections"] == [] and out["status"] == "no_verified_sections"
    assert [u["round"] for u in st["unconfirmed"]] == [0, 1, 2]


def test_empty_retry_ends_the_loop(g, scripted):
    llm = scripted(["303", "999"], [])
    st = _run(g, llm)["state"]
    assert len(llm.calls) == 2 and [v["section"] for v in st["verified_sections"]] == ["303"]


def test_wrong_code_named_never_verifies_even_when_number_exists(g, scripted):
    llm = scripted(["IPC 302"], ["103"])
    st = _run(g, llm)["state"]
    assert [v["section"] for v in st["verified_sections"]] == ["103"]
    assert all(v["code"] == "bns" for v in st["verified_sections"])


def test_era_follows_the_router(g, scripted):
    out = _run(g, scripted(["379", "34"]), date="2023-12-03")
    assert out["era"] == "ipc"
    assert [(v["code"], v["section"]) for v in out["state"]["verified_sections"]] == \
        [("ipc", "379"), ("ipc", "34")]


def test_insufficient_data_returns_early_without_llm(g, scripted):
    llm = scripted(["303"])
    out = _run(g, llm, sufficient=False)
    assert out["status"] == "insufficient_data" and llm.calls == []
    assert out["state"]["verified_sections"] == []


def test_no_proposals_is_explicit(g, scripted):
    assert _run(g, scripted([]))["status"] == "no_proposals"


def test_decline_needs_no_offence_and_no_sections(g, scripted):
    llm = scripted([], profile={"discloses_offence": False, "why": "a rent dispute"})
    out = _run(g, llm)
    assert out["status"] == "no_offence_disclosed" and out["state"]["candidate_sections"] == []
    assert out["state"]["facts_profile"]["why"] == "a rent dispute" and len(llm.calls) == 1


def test_contradictory_decline_is_overridden_not_obeyed(g, scripted):
    # "no offence" but a section proposed: the case must NOT be declined
    llm = scripted(["303"], profile={"discloses_offence": False, "why": "unclear"})
    out = _run(g, llm)
    assert out["status"] == "ok" and [v["section"] for v in out["state"]["verified_sections"]] == ["303"]
    assert out["state"]["facts_profile"]["decline_overridden"] is True
    assert "NOT declined" in out["state"]["warnings"][0]


def _joint(n, together=True, plan=True):
    return {"discloses_offence": True, "accused_count": n, "acted_together": together,
            "shared_plan_or_object": plan}


def test_four_accused_acting_together_get_common_intention_not_assembly(g, scripted):
    st = _run(g, scripted(["323"], profile=_joint(4)), date="2023-12-03")["state"]
    rule = [c for c in st["candidate_sections"] if c["source"] == "rule"]
    assert [c["raw"] for c in rule] == ["IPC 34"]
    assert {v["section"] for v in st["verified_sections"]} == {"323", "34"}


def test_bns_joint_liability_is_sub_section_3_5(g, scripted):
    st = _run(g, scripted(["115"], profile=_joint(3)))["state"]
    assert [(v["section"], v["subsection"]) for v in st["verified_sections"]] == [("115", None), ("3", "3(5)")]


def test_five_accused_with_common_object_get_unlawful_assembly_rule(g, scripted):
    st = _run(g, scripted(["323"], profile=_joint(5)), date="2023-12-03")["state"]
    assert [c["raw"] for c in st["candidate_sections"] if c["source"] == "rule"] == ["IPC 149"]


def test_no_liability_rule_without_joint_action_or_shared_plan(g, scripted):
    for prof in (_joint(1), _joint(3, together=False), _joint(3, plan=False), {}):
        st = _run(g, scripted(["323"], profile=prof), date="2023-12-03")["state"]
        assert not [c for c in st["candidate_sections"] if c["source"] == "rule"]


def test_liability_rule_does_not_duplicate_a_proposal(g, scripted):
    st = _run(g, scripted(["323", "34"], profile=_joint(4)), date="2023-12-03")["state"]
    assert [c["source"] for c in st["candidate_sections"]] == ["llm", "llm"]


def test_applicability_splits_charges_from_unsupported(g, scripted):
    llm = scripted(["303", "302"], assess={
        "BNS 302": {"facts_quotes": ["rode away"], "missing_ingredient": "no words about religion",
                    "applies": False}})
    out = _run(g, llm)
    assert [v["section"] for v in out["charges"]] == ["303"]
    assert [v["section"] for v in out["unsupported"]] == ["302"]
    # both stay verified -- the check adds a verdict, it never deletes
    assert [v["section"] for v in out["state"]["verified_sections"]] == ["303", "302"]
    assert len(llm.assess_calls) == 2          # two self-consistency passes


def test_invented_quote_never_supports_a_section(g, scripted):
    llm = scripted(["303"], assess={
        "BNS 303": {"facts_quotes": ["the accused broke the lock at midnight"],   # not in FACTS
                    "missing_ingredient": "", "applies": True}})
    out = _run(g, llm)
    a = out["state"]["applicability"][0]
    assert not a["supported"] and a["grounded_quotes"] == [] and out["charges"] == []
    assert a["dropped_quotes"] == ["the accused broke the lock at midnight"]


def test_quote_matching_ignores_case_whitespace_and_curly_quotes(g, scripted):
    llm = scripted(["303"], assess={"BNS 303": {
        "facts_quotes": ["THE ACCUSED   TOOK the complainant’s motorcycle"],
        "missing_ingredient": "None.", "applies": True}})
    assert [v["section"] for v in _run(g, llm)["charges"]] == ["303"]


def test_named_missing_ingredient_defeats_support(g, scripted):
    llm = scripted(["303"], assess={"BNS 303": {
        "facts_quotes": ["took the complainant's motorcycle"],
        "missing_ingredient": "dishonest intention is not shown", "applies": True}})
    assert _run(g, llm)["charges"] == []


def test_headcount_rule_rejects_assembly_with_four_accused(g, scripted):
    # IPC 149 needs five or more persons; the model may say it applies, the rule decides.
    llm = scripted(["323", "34"], profile={**_joint(4)})
    st = _run(g, llm, date="2023-12-03")["state"]
    from src.pipeline import applicability as ap
    assert ap.headcount_rule("ipc", "149", st["facts_profile"]) == \
        "an unlawful assembly needs five or more persons; the facts show 4"
    assert ap.headcount_rule("ipc", "149", {"accused_count": 5}) is None
    assert ap.headcount_rule("ipc", "149", {"accused_count": 0}) is None      # unknown count
    assert ap.headcount_rule("bns", "3", {"accused_count": 1}).startswith("joint liability")
    assert ap.headcount_rule("ipc", "302", {"accused_count": 1}) is None


def test_nothing_missing_phrasings():
    from src.pipeline.applicability import nothing_missing as nm
    for t in ("", "None", "None; all ingredients are present.", "N/A", "No ingredient is missing",
              "All essential ingredients are shown."):
        assert nm(t), t
    for t in ("Nothing is shown about intent", "The facts do not show dishonest intention"):
        assert not nm(t), t


def test_applicability_check_off_is_phase4_behaviour(g, scripted):
    llm = scripted(["303", "302"])
    out = _run(g, llm, check_applicability=False)
    assert llm.assess_calls == [] and [v["section"] for v in out["charges"]] == ["303", "302"]


def test_no_applicability_call_when_nothing_verified(g, scripted):
    llm = scripted(["379A"])
    out = _run(g, llm)
    assert llm.assess_calls == [] and out["state"]["applicability"] == []


def test_final_state_keeps_every_section3_field(g, scripted):
    st = _run(g, scripted(["303"]))["state"]
    assert set(SECTION3_FIELDS) <= set(st)


def test_straddling_period_runs_both_codes_with_warning(g, scripted):
    out = graph.run(FACTS, "2024-01-10", offence_date_to="2024-09-10", llm=scripted(["379", "303"]), g=g,
                    retrieve=lambda f, era: RETRIEVED, sufficient=lambda f, era: (True, {}),
                    text_of=lambda era, sec, sub: "text")
    assert out["status"] == "straddles_transition" and set(out["runs"]) == {"ipc", "bns"}
    assert out["runs"]["ipc"]["era"] == "ipc" and out["runs"]["bns"]["era"] == "bns"
    assert [v["section"] for v in out["runs"]["ipc"]["state"]["verified_sections"]] == ["379"]
    assert [v["section"] for v in out["runs"]["bns"]["state"]["verified_sections"]] == ["303"]
    assert "straddles" in out["warnings"][0] and out["runs"]["bns"]["state"]["warnings"]


def test_period_on_one_side_is_a_single_run(g, scripted):
    out = graph.run(FACTS, "2024-07-05", offence_date_to="2024-09-10", llm=scripted(["303"]), g=g,
                    retrieve=lambda f, era: RETRIEVED, sufficient=lambda f, era: (True, {}),
                    text_of=lambda era, sec, sub: "text")
    assert out["era"] == "bns" and out["status"] == "ok"


def test_a_section_is_demoted_only_if_every_pass_rejects_it(g, scripted):
    from src.pipeline import applicability as ap

    class FlipLLM:
        """Rejects whichever section is listed FIRST -- an order-sensitive judge."""
        def __call__(self, messages, schema):
            refs = re.findall(r"^\[([^\]]+)\]", messages[-1]["content"], re.M)
            q = {"facts_quotes": ["took the complainant's motorcycle"], "missing_ingredient": ""}
            return {"assessments": [{"section": r, **q, "applies": i > 0} for i, r in enumerate(refs)]}

    st = {"era": "bns", "case_facts": FACTS, "facts_profile": {},
          "verified_sections": [{"section": "303", "subsection": None, "title": "Theft"},
                                {"section": "302", "subsection": None, "title": "x"}]}
    one = ap.assess(st, FlipLLM(), text_of=lambda *a: "t", passes=1)["applicability"]
    two = ap.assess(st, FlipLLM(), text_of=lambda *a: "t", passes=2)["applicability"]
    assert [a["supported"] for a in one] == [False, True]      # single pass: order decides
    assert [a["supported"] for a in two] == [True, True]       # consensus: neither demoted
    assert two[0]["passes"] == [False, True]
