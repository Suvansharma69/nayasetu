"""Intake: court orders are reduced to their alleged facts; fact statements are untouched."""
from src.pipeline import graph, intake

ORDER = ("Heard learned counsel for the petitioner and the A.P.P. for the State. The petitioner is "
         "apprehending arrest in Barh P.S. Case No. 12 of 2011 registered under Section 438 Cr.P.C. "
         "The accusation is that the petitioner struck the informant with a lathi and took away his goat.")
FACTS = "The accused took the complainant's motorcycle without consent and rode away."


def test_trigger_separates_orders_from_fact_statements():
    assert intake.looks_procedural(ORDER)
    assert not intake.looks_procedural(FACTS)


def test_fact_statement_is_passed_through_without_an_llm_call():
    def boom(*a):
        raise AssertionError("LLM called")
    assert intake.extract(FACTS, boom) == {"facts": FACTS, "extracted": False, "why": "reads as a fact statement"}


def test_order_is_reduced_to_its_alleged_facts():
    out = intake.extract(ORDER, lambda m, s: {"alleged_facts": "The accused struck the informant with a lathi and took away his goat."})
    assert out["extracted"] and "438" not in out["facts"] and "goat" in out["facts"]


def test_an_extraction_that_invents_facts_falls_back_to_the_original():
    out = intake.extract(ORDER, lambda m, s: {"alleged_facts": "The accused fired a revolver at a jeweller and fled with diamonds."})
    assert not out["extracted"] and out["facts"] == ORDER and "original used" in out["why"]


def test_pipeline_reads_the_extracted_facts_and_keeps_the_original(g, scripted):
    base = scripted(["379"])
    seen = []

    def llm(messages, schema):
        if "alleged_facts" in schema["properties"]:
            return {"alleged_facts": "The accused struck the informant with a lathi and took away his goat."}
        seen.append(messages[-1]["content"])
        return base(messages, schema)

    out = graph.run(ORDER, "2011-05-01", llm=llm, g=g, retrieve=lambda f, era: [],
                    sufficient=lambda f, era: (True, {}), check_applicability=False)
    assert out["intake"]["extracted"] and out["intake"]["original_input"] == ORDER
    assert out["state"]["case_facts"].startswith("The accused struck")
    assert all("438" not in m for m in seen)


def test_an_order_with_no_facts_says_so_and_keeps_the_original():
    out = intake.extract(ORDER, lambda m, s: {"facts_stated": False, "alleged_facts": ""})
    assert not out["extracted"] and out["facts"] == ORDER and "no alleged facts" in out["why"]
    assert out["no_facts"]


PROCEDURE_ONLY = ("Heard learned counsel for the petitioner and learned counsel for the State. The "
                  "petitioner apprehends his arrest in connection with Jakkanpur P.S. Case No. 279/2011. "
                  "Learned counsel seeks permission to withdraw this application. Permission is granted.")


def _no_facts_llm(messages, schema):
    if "alleged_facts" in schema["properties"]:
        return {"facts_stated": False, "alleged_facts": ""}
    raise AssertionError("Node 1 was asked to charge a text that states no facts")


def test_an_order_with_no_facts_is_not_charged(g):
    """Phase 6: run anyway, Node 1 charged IPC 173/174/204/224 for a withdrawn bail plea."""
    out = graph.run(PROCEDURE_ONLY, "2011-05-01", llm=_no_facts_llm, g=g,
                    retrieve=lambda f, era: [{"section": "174", "title": "Non-attendance"}],
                    sufficient=lambda f, era: (True, {}))
    assert out["status"] == "insufficient_data" and out["charges"] == []
    assert out["guardrail"]["reason"] == "no_facts_stated" and "FIR" in out["guardrail"]["message"]
    assert out["review_candidates"] == []        # procedural sections would read as suggestions
    assert out["era"] == "ipc" and out["intake"]["original_input"] == PROCEDURE_ONLY


def test_a_flag_without_an_empty_extraction_is_not_a_decline(g, scripted):
    """One boolean never erases the rest of the answer (Known Gotchas, 2026-09-27)."""
    base = scripted(["379"])

    def llm(messages, schema):
        if "alleged_facts" in schema["properties"]:
            return {"facts_stated": False, "alleged_facts": "The accused took away the informant's goat at night."}
        return base(messages, schema)

    out = graph.run(PROCEDURE_ONLY + " The accusation is that he took away the informant's goat at night.",
                    "2011-05-01", llm=llm, g=g, retrieve=lambda f, era: [],
                    sufficient=lambda f, era: (True, {}), check_applicability=False)
    assert out["status"] != "insufficient_data"


def test_no_facts_switch_restores_the_old_behaviour(g, scripted, monkeypatch):
    monkeypatch.setenv("PRAMANA_ABLATE", "nofacts")
    base = scripted(["379"])

    def llm(messages, schema):
        if "alleged_facts" in schema["properties"]:
            return {"facts_stated": False, "alleged_facts": ""}
        return base(messages, schema)

    out = graph.run(PROCEDURE_ONLY, "2011-05-01", llm=llm, g=g, retrieve=lambda f, era: [],
                    sufficient=lambda f, era: (True, {}), check_applicability=False)
    assert (out.get("guardrail") or {}).get("reason") != "no_facts_stated"
