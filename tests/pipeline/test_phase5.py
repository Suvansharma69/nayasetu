"""Phase 5 nodes: precedent matcher (Node 3), defence + final verification
(Node 4), outcome analytics (Node 5), and the full graph wired together."""
import sqlite3

import pytest

from src.graph import citation_graph as cg
from src.pipeline import analytics, defense, graph, precedents

FACTS = "The accused took the complainant's motorcycle without consent and rode away."
RETRIEVED = [{"section": "303", "title": "Theft", "matched": "303(2)", "excerpt": "Whoever ..."}]


def _add_case(g, doc_id, code, section, chunks=1, title=None):
    key = cg.case_key(doc_id)
    g.add_node(key, kind="case", doc_id=doc_id, title=title, court="SC", disposal_nature="Dismissed")
    g.add_edge(key, cg.section_key(code, section), kind="cites", chunks=chunks)
    g.graph["case_index"] = cg._case_index(g)


def _state(era="bns", verified=("303",), pool=None, precs=None, facts=FACTS):
    return {"era": era, "case_facts": facts, "precedent_pool": pool or {}, "applicability": [],
            "verified_sections": [{"section": s, "subsection": None, "title": "t"} for s in verified],
            "precedents": precs or []}


# --- Node 3 ---------------------------------------------------------------------

def test_bns_charge_gets_ipc_predecessor_precedent_ordered_by_similarity(g):
    _add_case(g, "old_popular", "ipc", "379", chunks=50)
    _add_case(g, "old_similar", "ipc", "378", chunks=1)
    pool = {"old_similar": {"score": 0.7, "chunk_id": "c", "text": "motorcycle taken at night"}}
    out = precedents.precedent_matcher(_state(pool=pool), g)["precedents"]
    assert [p["doc_id"] for p in out] == ["old_similar", "old_popular"]
    assert out[0]["via_ipc_predecessor"] == "BNS 303 <- IPC 378"
    assert out[0]["matched_by"] == "similarity to the facts" and out[1]["matched_by"] == "most cited"
    assert [p["label"] for p in out] == ["P1", "P2"] and all(p["verified"] for p in out)


def test_precedent_needs_a_graph_edge_similarity_alone_is_not_enough(g):
    pool = {"unrelated": {"score": 0.99, "chunk_id": "c", "text": "very similar text"}}
    assert precedents.precedent_matcher(_state(pool=pool), g)["precedents"] == []


def test_companion_judgments_with_identical_text_are_shown_once(g):
    for d in ("a1", "a2"):
        _add_case(g, d, "ipc", "379")
    pool = {d: {"score": 0.6, "chunk_id": d, "text": "same appeal text"} for d in ("a1", "a2")}
    assert len(precedents.precedent_matcher(_state(pool=pool), g)["precedents"]) == 1


def test_companion_judgments_differing_only_in_a_date_are_shown_once(g):
    base = ("This appeal is directed against the judgment of the learned Additional District Judge "
            "in of 2017, dated {} whereby the appellant was convicted for the offence punishable "
            "under Section 379 and sentenced to simple imprisonment for a period of six months.")
    texts = {"b1": base.format(""), "b2": base.format("16.04.2019,"), "b3": "A wholly different appeal "
             "about a stolen bicycle taken from the railway station parking lot at night by two men."}
    for d in texts:
        _add_case(g, d, "ipc", "379")
    pool = {d: {"score": 0.6, "chunk_id": d, "text": t} for d, t in texts.items()}
    out = precedents.precedent_matcher(_state(pool=pool), g)["precedents"]
    assert sorted(p["doc_id"] for p in out) in (["b1", "b3"], ["b2", "b3"])


# --- Node 4 final verification -------------------------------------------------------

def test_final_check_flags_uncharged_section_unknown_precedent_and_invented_quote(g):
    _add_case(g, "real", "ipc", "379")
    st = _state(precs=[{"label": "P1", "doc_id": "real", "title": "Real v State"}])
    out = defense.verify_arguments(st, [
        {"against": "BNS 303", "argument": "ok", "fact_quote": "rode away", "precedents": ["P1"]},
        {"against": "BNS 318", "argument": "x", "fact_quote": "", "precedents": []},
        {"against": "303", "argument": "x", "fact_quote": "", "precedents": ["P9"]},
        {"against": "303", "argument": "x", "fact_quote": "he confessed to the police", "precedents": []},
    ], g)
    assert out[0]["verified"] and out[0]["precedents"][0]["doc_id"] == "real"
    assert not out[1]["verified"] and "not a verified charge" in out[1]["issues"][0]
    assert not out[2]["verified"] and "P9" in out[2]["issues"][0]
    assert not out[3]["verified"] and out[3]["fact_quote"] == ""


def test_no_verified_section_means_no_llm_call(g):
    def boom(*a):
        raise AssertionError("LLM called")
    assert defense.defense_generator(_state(verified=()), boom, g) == {"defenses": []}


# --- Node 5 ----------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    path = tmp_path / "o.sqlite"
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE cases (doc_id TEXT, court TEXT, source TEXT, year INT, disposal_raw TEXT,"
                      " disposal TEXT, title TEXT); CREATE TABLE cites (doc_id TEXT, code TEXT, section TEXT);")
    for i in range(6):
        con.execute("INSERT INTO cases VALUES (?,?,?,?,?,?,?)",
                    (f"d{i}", "SC", "x", 2020, None, "allowed" if i < 2 else "dismissed", None))
        con.execute("INSERT INTO cites VALUES (?,?,?)", (f"d{i}", "ipc", "379"))
    con.execute("INSERT INTO cites VALUES ('d0','bns','303')")
    con.commit()
    con.close()
    return path


def test_disposal_buckets():
    assert analytics.bucket("Appeal(s) allowed") == "allowed"
    assert analytics.bucket("Case Partly allowed") == "partly allowed"
    assert analytics.bucket("Dismissed") == "dismissed"
    assert analytics.bucket("Disposed off") == analytics.bucket(None) == "other"


def test_small_samples_suppressed_and_bns_shows_ipc_predecessor(g, db):
    a = analytics.outcome_analytics(_state(), g=g, db_path=db)["analytics"]
    s = a["sections"][0]
    assert s["direct"]["judgments"] == 1 and s["direct"]["suppressed"] and "allowed_share" not in s["direct"]
    via = {v["section"]: v for v in s["via_ipc"]}
    assert via["379"]["judgments"] == 6 and not via["379"]["suppressed"]
    assert via["379"]["allowed_share"] == pytest.approx(2 / 6, abs=1e-3)
    assert "Not a conviction rate" in a["note"]


# --- wired together ---------------------------------------------------------------------

def test_full_graph_runs_nodes_3_to_5(g, db, scripted, monkeypatch):
    monkeypatch.setattr(analytics, "DB_PATH", db)
    _add_case(g, "theft_case", "ipc", "379")
    base = scripted(["303"])

    def llm(messages, schema):
        if "arguments" in schema["properties"]:
            return {"arguments": [{"against": "BNS 303", "argument": "intent not shown",
                                   "fact_quote": "rode away", "precedents": ["P1"]}]}
        return base(messages, schema)

    out = graph.run(FACTS, "2024-08-15", llm=llm, g=g, retrieve=lambda f, era: RETRIEVED,
                    sufficient=lambda f, era: (True, {}), text_of=lambda era, s, sub=None: "Whoever ...",
                    full=True)
    st = out["state"]
    assert [v["section"] for v in st["verified_sections"]] == ["303"]
    assert [p["doc_id"] for p in st["precedents"]] == ["theft_case"]
    assert st["analytics"]["sections"][0]["charge"] == "BNS 303"
    assert st["defenses"][0]["verified"] and st["defenses"][0]["precedents"][0]["label"] == "P1"
