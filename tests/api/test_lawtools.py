import os

import networkx as nx
import pytest

from src.api import assistant, lawtools
from src.graph import citation_graph as cg


# --- punishment, read off the section's own words -----------------------------------

def test_punishment_terms():
    p = lawtools.punishment("Whoever commits theft shall be punished with imprisonment of either description "
                            "for a term which may extend to three years, or with fine, or with both.")
    assert p["max"] == "3 years" and p["min"] is None and len(p["sentences"]) == 1
    p = lawtools.punishment("Whoever commits murder shall be punished with death, or imprisonment for life, "
                            "and shall also be liable to fine.")
    assert p["max"] == "death"
    p = lawtools.punishment("shall be punished with imprisonment for a term which shall not be less than seven "
                            "years but which may extend to imprisonment for life.")
    assert p["max"] == "imprisonment for life" and p["min"] == "7 years"


def test_death_in_the_offence_is_not_a_death_sentence():
    # BNS 118: "...any instrument which, used as a weapon of offence, is likely to cause death, ... shall be punished
    # with imprisonment ... which may extend to three years" -- not a death sentence.
    p = lawtools.punishment("Whoever voluntarily causes hurt by any instrument which is likely to cause death, "
                            "shall be punished with imprisonment for a term which may extend to three years.")
    assert p["max"] == "3 years"


def test_unreadable_term_is_not_guessed():
    p = lawtools.punishment("shall be punished as provided in the preceding section.")
    assert p["max"] is None and p["sentences"]


# --- comparison text ------------------------------------------------------------------

def test_core_drops_notes_but_keeps_later_subsections():
    t = ("303. (1) Whoever moves property is said to commit theft. Explanation 1.— A thing attached is not "
         "movable. Illustrations. (a) A cuts down a tree. (2) Whoever commits theft shall be punished with fine.")
    c = lawtools.core(t)
    assert "Explanation" not in c and "Illustration" not in c and "cuts down" not in c
    assert c.startswith("Whoever moves property") and "shall be punished with fine" in c


def test_word_diff_marks_only_changes():
    d = lawtools.word_diff("shall be punished for three years", "shall be punished for five years")
    assert ["del", "three"] in d and ["ins", "five"] in d
    assert all(op in ("eq", "del", "ins") for op, _ in d)


# --- citations in a follow-up answer --------------------------------------------------

@pytest.fixture
def g():
    g = nx.DiGraph()
    for code, sec, title in [("bns", "303", "Theft"), ("bns", "318", "Cheating"), ("ipc", "379", "Punishment for theft")]:
        g.add_node(cg.section_key(code, sec), kind="section", code=code, section=sec, title=title)
    return g


REPORT = {"era": "bns", "facts": "The accused took the motorcycle.", "code_applied": "BNS",
          "charges": [{"code": "BNS", "section": "303", "subsection": None, "title": "Theft", "reason": "r", "doubt": None}],
          "precedents": [{"label": "P1", "doc_id": "d1", "for_charge": "BNS 303", "excerpt": "x"}], "defenses": []}


def test_citations_are_checked_against_the_graph(g):
    text = ("BNS 303 applies; its predecessor was Section 379 of the IPC. BNS 420 does not exist. "
            "Bail is under Section 480 of the BNSS.")
    out = {(c["code"], c["section"]): c for c in assistant.check_citations(text, "bns", g, REPORT)}
    assert out[("bns", "303")]["status"] == "verified" and out[("bns", "303")]["in_report"]
    assert out[("ipc", "379")]["status"] == "verified"           # code read from "of the IPC"
    assert out[("bns", "420")]["status"] == "unconfirmed"        # the renumbering trap
    assert out[(None, "480")]["status"] == "other_act"           # BNSS: not a penal-code citation


def test_ask_flags_unknown_precedent_labels(g):
    llm = lambda msgs, schema, **kw: {"answer": "Under BNS 303 the strongest authority is [P1]; see also [P7]."}  # noqa: E731
    out = assistant.ask(REPORT, "Which precedent helps?", llm, g)
    assert {(p["label"], p["valid"]) for p in out["precedents"]} == {("P1", True), ("P7", False)}
    assert out["citations"][0]["status"] == "verified"


def test_ask_material_is_only_the_report(g):
    msgs = assistant.ask_messages(REPORT, "Why?", history=[("q1", "a1")])
    assert "The accused took the motorcycle." in msgs[1]["content"] and "[P1]" in msgs[1]["content"]
    assert msgs[-1]["content"] == "QUESTION: Why?" and msgs[-2]["content"] == "a1"


def test_summary_quote_must_be_verbatim(g, monkeypatch):
    g.add_node(cg.case_key("d1"), kind="case", doc_id="d1")
    monkeypatch.setattr(cg, "verify_case", lambda g, i: i == "d1")
    text = "The appellant was convicted of theft. We hold that dishonest intention was proved. Appeal dismissed."
    monkeypatch.setattr(assistant, "judgment_text", lambda doc_id, cli=None: (text, {"court": "SC"}))
    assistant._cache.clear()
    reply = {"facts": "f", "question": "q", "held": "h", "outcome": "dismissed",
             "key_quote": "We hold that dishonest intention was proved."}
    out = assistant.summarise("d1", lambda m, s, **kw: reply, g)
    assert out["quote_checked"] and out["key_quote"]
    assistant._cache.clear()
    out = assistant.summarise("d1", lambda m, s, **kw: {**reply, "key_quote": "Intention was plainly proved."}, g)
    assert not out["quote_checked"] and out["key_quote"] == "" and out["quote_dropped"]
    with pytest.raises(LookupError):
        assistant.summarise("nope", lambda m, s, **kw: reply, g)


# --- on the real ingested data, when it is present -------------------------------------

REAL = os.path.exists(cg.graph_path())


@pytest.mark.skipif(not REAL, reason="citation graph not built")
def test_real_sections_and_mapping():
    rg = cg.load()
    info = lawtools.section_info(rg, "ipc", "379")
    assert info["punishment"]["max"] == "3 years" and info["counterparts"][0]["section"] == "303"
    assert lawtools.section_info(rg, "bns", "420") is None                       # not a BNS section
    assert lawtools.section_info(rg, "ipc", "304B")["counterparts"][0]["section"] == "80"
    c = lawtools.compare(rg, "ipc", "420")
    assert c["versus"] == "318(4)" and c["changed_share"] < 0.2                     # 420 carried over almost verbatim
    c = lawtools.compare(rg, "ipc", "406")
    assert ["del", "three"] in c["diff"] and ["ins", "five"] in c["diff"]        # CBT: 3 -> 5 years


@pytest.mark.skipif(not (REAL and lawtools.SCHEDULE.exists()), reason="graph or First Schedule not built")
def test_real_first_schedule_rows():
    # Pins the parse of the official Schedules (scripts/build_schedule.py), not memory:
    # if a parser change moves any of these, the change is wrong or the source changed.
    s = lawtools.schedule_for("bns", "303")
    assert [(r["ref"], r["cognizable_flag"], r["bailable_flag"]) for r in s["rows"]] == [
        ("303(2)", "yes", "no"), ("303(2)", "no", "yes")]        # theft; and under 5,000 rupees
    assert {r["ref"]: r["bailable_flag"] for r in lawtools.schedule_for("bns", "318")["rows"]} == {
        "318(2)": "yes", "318(3)": "yes", "318(4)": "no"}
    ipc = {s: lawtools.schedule_for("ipc", s)["rows"][0] for s in ("323", "326", "379", "498A")}
    assert (ipc["323"]["cognizable_flag"], ipc["323"]["bailable_flag"]) == ("no", "yes")
    assert ipc["326"]["bailable_flag"] == "no" and ipc["379"]["triable"] == "Any Magistrate."
    assert ipc["498A"]["cognizable_flag"] == "conditional"
    assert lawtools.schedule_for("ipc", "222")["rows"][0]["bailable_flag"] == "unclear"   # a defect in the source
    assert lawtools.schedule_for("bns", "999") is None


def test_schedule_max_reads_every_limb():
    rows = {"rows": [{"punishment": "Imprisonment for 2 years, or fine, or both."},
                     {"punishment": "Imprisonment for 7 years, or fine, or both."}]}
    assert lawtools.schedule_max(rows) == "7 years"
    assert lawtools.schedule_max({"rows": [{"punishment": "Death, or imprisonment for 10 years and fine."}]}) == "death"
    assert lawtools.schedule_max({"rows": [{"punishment": "Rigorous imprisonment for not less than 10 years but "
                                                          "which may extend to imprisonment for life"}]}) == "imprisonment for life"
    assert lawtools._rank("death") > lawtools._rank("imprisonment for life") > lawtools._rank("14 years") > lawtools._rank("7 years")


def test_a_named_offence_is_not_the_penalty():
    # BNS 351: the threat is "to cause an offence punishable with death"; the penalty is 7 years.
    p = lawtools.punishment("Whoever commits criminal intimidation by threatening to cause an offence punishable with "
                            "death or imprisonment for life shall be punished with imprisonment of either description "
                            "for a term which may extend to seven years, or with fine, or with both.")
    assert p["max"] == "7 years"


@pytest.mark.skipif(not (REAL and lawtools.SCHEDULE.exists()), reason="graph or First Schedule not built")
def test_real_maxima_survive_truncated_ipc_text():
    rg = cg.load()
    p506 = lawtools.section_info(rg, "ipc", "506")["punishment"]
    # 506's threat-to-kill limb was missing upstream and the Schedule supplied the
    # 7 years; since 2026-10-07 the official text completes it (statute_patches.json).
    assert not p506["text_incomplete"] and p506["max"] == "7 years"
    assert lawtools.section_info(rg, "ipc", "307")["punishment"]["max"] == "death"
    assert lawtools.section_info(rg, "bns", "351")["punishment"]["max"] == "7 years"
