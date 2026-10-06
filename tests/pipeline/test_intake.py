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
