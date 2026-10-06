"""The LangGraph loop end to end, with a scripted LLM and injected retrieval.

These are the mechanics behind the Phase 4 gate: the retry edge fires on an
unconfirmed section, feeds it back, caps at retry_count < 2, and never lets an
unconfirmed section into verified_sections."""
import re

import pytest

from src.pipeline import graph, nodes
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
    assert out["state"]["verified_sections"] == [] and out["charges"] == []


def test_insufficient_data_is_never_a_bare_refusal(g, scripted):
    # Held-out 3 #7: the guardrail refused a real mischief case. The nearest
    # statute sections are still surfaced, unverified, and the LLM is not called.
    llm = scripted(["303"])
    out = _run(g, llm, sufficient=False)
    assert llm.calls == [] and [r["section"] for r in out["review_candidates"]] == ["303"]


def test_no_proposals_is_explicit(g, scripted):
    assert _run(g, scripted([]))["status"] == "no_proposals"


def test_the_model_can_never_decline_a_case(g, scripted):
    # "no offence" and nothing proposed: no decline status exists any more; the
    # report carries a warning and surfaces the retrieved sections for review.
    llm = scripted([], profile={"discloses_offence": False, "why": "a rent dispute"})
    out = _run(g, llm)
    assert out["status"] == "no_proposals"
    assert "may not disclose a criminal offence" in out["state"]["warnings"][0]
    assert "a rent dispute" in out["state"]["warnings"][0]
    assert [r["section"] for r in out["review_candidates"]] == ["303"]


def test_no_offence_view_with_sections_still_verifies_them(g, scripted):
    llm = scripted(["303"], profile={"discloses_offence": False, "why": "unclear"})
    out = _run(g, llm)
    assert out["status"] == "ok" and [v["section"] for v in out["state"]["verified_sections"]] == ["303"]
    assert out["state"]["warnings"] and out["review_candidates"] == []


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


def test_bare_bns_3_proposal_does_not_suppress_the_3_5_rule(g, scripted):
    # Dev case 15: the model proposed a bare "3" (general explanations, rejected
    # as non-chargeable) and that used to block the rule's 3(5).
    st = _run(g, scripted(["115", "3"], profile=_joint(3)))["state"]
    assert [c["raw"] for c in st["candidate_sections"] if c["source"] == "rule"] == ["BNS 3(5)"]
    assert ("3", "3(5)") in {(v["section"], v["subsection"]) for v in st["verified_sections"]}


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
    # advisory (the default): both stay charges; the doubt travels with 302
    assert [v["section"] for v in out["charges"]] == ["303", "302"]
    assert [(d["section"], d["doubt"]) for d in out["doubted"]] == [("302", "no words about religion")]
    assert [v["section"] for v in out["state"]["verified_sections"]] == ["303", "302"]
    assert len(llm.assess_calls) == 2          # two self-consistency passes
    # the gate, kept for comparison runs, removes it from charges
    gated = graph.split_by_applicability(out["state"], gates=True)
    assert [v["section"] for v in gated["charges"]] == ["303"]
    assert [v["section"] for v in gated["unsupported"]] == ["302"]


def test_invented_quote_never_supports_a_section(g, scripted):
    llm = scripted(["303"], assess={
        "BNS 303": {"facts_quotes": ["the accused broke the lock at midnight"],   # not in FACTS
                    "missing_ingredient": "", "applies": True}})
    out = _run(g, llm)
    a = out["state"]["applicability"][0]
    assert not a["supported"] and a["grounded_quotes"] == []
    assert [d["section"] for d in out["doubted"]] == ["303"]
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
    out = _run(g, llm)
    assert [(d["section"], d["doubt"]) for d in out["doubted"]] == [("303", "dishonest intention is not shown")]
    assert graph.split_by_applicability(out["state"], gates=True)["charges"] == []


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


def test_a_section_is_supported_only_if_every_pass_supports_it(g, scripted, monkeypatch):
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
    # Advisory judge (UNANIMOUS): a split verdict is a doubt, not support.
    assert [a["supported"] for a in two] == [False, False]
    assert two[0]["passes"] == [False, True]
    monkeypatch.setattr(ap, "UNANIMOUS", False)                # the gate-era rule: any pass
    two = ap.assess(st, FlipLLM(), text_of=lambda *a: "t", passes=2)["applicability"]
    assert [a["supported"] for a in two] == [True, True]


def test_ablation_switches(g, scripted, monkeypatch):
    monkeypatch.setenv("PRAMANA_ABLATE", "judge,profile")
    llm = scripted(["323"], profile=_joint(4))
    out = _run(g, llm, date="2023-12-03")
    assert llm.assess_calls == []                                   # judge off
    assert not [c for c in out["state"]["candidate_sections"] if c["source"] == "rule"]   # profile off
    monkeypatch.setenv("PRAMANA_ABLATE", "nonsense")
    with pytest.raises(ValueError):
        _run(g, scripted(["323"]))


def test_node1_union_of_two_candidate_orderings(g, monkeypatch):
    monkeypatch.setattr(nodes, "NODE1_UNION", True)                # off by default
    two =[{"section": "303", "title": "Theft", "matched": "303", "excerpt": "x"},
           {"section": "318", "title": "Cheating", "matched": "318", "excerpt": "y"}]

    class OrderLLM:
        """Proposes whichever candidate it reads first -- an order-sensitive model."""
        def __init__(self):
            self.prompts = []

        def __call__(self, messages, schema):
            if "assessments" in schema["properties"]:
                return {"assessments": []}
            user = messages[1]["content"]
            self.prompts.append(user)
            first = "303" if user.find("BNS 303") < user.find("BNS 318") else "318"
            return {"sections": [{"section": first, "reason": "r"}, {"section": "303", "reason": "r"}]}

    llm = OrderLLM()
    out = graph.run(FACTS, "2024-08-15", llm=llm, g=g, retrieve=lambda f, era: two,
                    sufficient=lambda f, era: (True, {}), text_of=lambda *a: "t")
    assert len(llm.prompts) == 2                                   # original + reversed order
    raws = [c["raw"] for c in out["state"]["candidate_sections"]]
    assert sorted(raws) == ["303", "318"]                          # union, duplicates collapsed


def test_node1_asks_once_by_default(g, scripted):
    two = [{"section": "303", "title": "Theft", "matched": "303", "excerpt": "x"},
           {"section": "318", "title": "Cheating", "matched": "318", "excerpt": "y"}]
    llm = scripted(["303"])
    graph.run(FACTS, "2024-08-15", llm=llm, g=g, retrieve=lambda f, era: two,
              sufficient=lambda f, era: (True, {}), text_of=lambda *a: "t")
    assert len(llm.calls) == 1                                     # no second ordering


# --- VRAM handoff: query encoded on the GPU only after Ollama lets go ---------

def test_injected_retrieval_never_touches_ollama_or_the_gpu(monkeypatch):
    from src.pipeline import graph as gr
    called = []
    monkeypatch.setattr(gr.llm_mod, "unload", lambda *a, **k: called.append(1))
    monkeypatch.setattr(gr, "RUNTIME_DEVICE", "cuda")
    assert gr._encode_device(uses_embedder=False) == "cpu" and not called


def test_cpu_setting_skips_the_unload(monkeypatch):
    from src.pipeline import graph as gr
    called = []
    monkeypatch.setattr(gr.llm_mod, "unload", lambda *a, **k: called.append(1))
    monkeypatch.setattr(gr, "RUNTIME_DEVICE", "cpu")
    assert gr._encode_device() == "cpu" and not called


def test_cuda_unloads_ollama_first(monkeypatch):
    import torch

    from src.pipeline import graph as gr
    called = []
    monkeypatch.setattr(gr.llm_mod, "unload", lambda *a, **k: called.append(1))
    monkeypatch.setattr(gr, "RUNTIME_DEVICE", "cuda")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert gr._encode_device() == "cuda" and called == [1]


def test_gpu_out_of_memory_falls_back_to_cpu(monkeypatch):
    import torch

    from src.pipeline import graph as gr
    monkeypatch.setattr(gr.embedder, "free", lambda: None)
    tried = []

    def fn(device):
        tried.append(device)
        if device == "cuda":
            raise torch.cuda.OutOfMemoryError("card is full")
        return "ok"

    assert gr._on_device(fn, "cuda") == "ok" and tried == ["cuda", "cpu"]
