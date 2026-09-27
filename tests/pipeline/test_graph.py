"""The LangGraph loop end to end, with a scripted LLM and injected retrieval.

These are the mechanics behind the Phase 4 gate: the retry edge fires on an
unconfirmed section, feeds it back, caps at retry_count < 2, and never lets an
unconfirmed section into verified_sections."""
from src.pipeline import graph
from src.pipeline.state import SECTION3_FIELDS

FACTS = "The accused took the complainant's motorcycle without consent and rode away."
RETRIEVED = [{"section": "303", "title": "Theft", "matched": "303(2)", "excerpt": "Whoever ..."}]


def _run(g, llm, date="2024-08-15", sufficient=True):
    return graph.run(FACTS, date, llm=llm, g=g, retrieve=lambda f, era: RETRIEVED,
                     sufficient=lambda f, era: (sufficient, {"top_similarity": 0.5}))


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


def test_final_state_keeps_every_section3_field(g, scripted):
    st = _run(g, scripted(["303"]))["state"]
    assert set(SECTION3_FIELDS) <= set(st)
