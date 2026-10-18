import networkx as nx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api import main, report, visuals
from src.graph import citation_graph as cg
from src.pipeline import embedmap


def _graph():
    """BNS 303 (no direct cases) <- IPC 378/379; three cases cite 379, two of them also 411."""
    g = nx.DiGraph()
    for code, sec, title in [("bns", "303", "Theft"), ("ipc", "378", "Theft"), ("ipc", "379", "Punishment for theft"),
                             ("ipc", "411", "Dishonestly receiving stolen property"), ("ipc", "34", "Common intention")]:
        g.add_node(cg.section_key(code, sec), kind="section", code=code, section=sec, title=title)
    for i, (court, date) in enumerate([("Supreme Court of India", "2024-03-01"), ("Madras High Court", None),
                                       ("Delhi High Court", None)]):
        key = cg.case_key(f"doc{i}")
        g.add_node(key, kind="case", doc_id=f"doc{i}", court=court, date=date, decision_year_min=2021,
                   title="A versus B" if i == 0 else None, disposal_nature="Dismissed", collection="judgments_pre2024")
        g.add_edge(key, "ipc:379", kind="cites", chunks=3 - i)
        if i < 2:
            g.add_edge(key, "ipc:411", kind="cites", chunks=1)
    g.add_edge("ipc:378", "bns:303", kind="maps_to")
    g.add_edge("ipc:379", "bns:303", kind="maps_to")
    g.graph["case_index"] = {f"doc{i}": cg.case_key(f"doc{i}") for i in range(3)}
    return g


def test_neighbourhood_bridges_bns_to_ipc_precedent():
    n = visuals.neighbourhood(_graph(), "bns", ["303"], doc_ids=["doc1"])
    ids = {x["id"]: x for x in n["nodes"]}
    assert ids["bns:303"]["role"] == "charge"
    assert ids["ipc:378"]["role"] == ids["ipc:379"]["role"] == "counterpart"
    # the report's own precedent is marked as such; the others are most-cited
    assert ids[cg.case_key("doc1")]["role"] == "precedent" and ids[cg.case_key("doc0")]["role"] == "cited"
    kinds = {(e["source"], e["target"], e["kind"]) for e in n["edges"]}
    assert ("ipc:379", "bns:303", "maps_to") in kinds and ("ipc:378", "bns:303", "maps_to") in kinds
    assert (cg.case_key("doc0"), "ipc:379", "cites") in kinds
    # 411 is cited by two of the judgments citing 379: a co-citation of weight 2
    co = [e for e in n["edges"] if e["kind"] == "co_cited"]
    assert co == [{"source": "ipc:379", "target": "ipc:411", "kind": "co_cited", "weight": 2}]
    assert ids[cg.case_key("doc1")]["year"] == "2021+"   # a lower bound, never shown as the decision year
    assert n["stats"] == {"sections": 4, "judgments": 3, "edges": {"maps_to": 2, "cites": 3, "co_cited": 1}}


def test_neighbourhood_skips_sections_that_do_not_exist():
    n = visuals.neighbourhood(_graph(), "bns", ["420", "303"])
    assert "bns:420" not in {x["id"] for x in n["nodes"]}
    assert visuals.neighbourhood(_graph(), "ipc", ["999"])["nodes"] == []
    with pytest.raises(ValueError):
        visuals.neighbourhood(_graph(), "both", ["303"])


def test_citation_check_counts_leaks_and_takes_the_last_rerun():
    recs = [
        {"id": "a", "status": "error: Ollama", "candidates": [], "verified": [], "unconfirmed": [], "charges": []},
        {"id": "a", "status": "ok", "candidates": [{"raw": "378"}, {"raw": "421"}],
         "verified": [{"section": "379"}], "unconfirmed": [{"raw": "421"}], "charges": ["379"]},
        {"id": "b", "status": "ok", "candidates": "[{'raw': '302', 'section': None}]",   # stored as a repr
         "verified": ["302"], "unconfirmed": "[]", "charges": ["302", "34"]},
    ]
    c = visuals.citation_check(recs)
    assert c == {"runs": 2, "proposals": 3, "rejected": 1, "runs_with_rejection": 1, "leaked": 1}


def test_report_keeps_the_ranking_signals():
    rows = [{"section": "303", "matched": "303(1)", "title": "Theft", "score": 0.0325, "statute_rank": 1,
             "statute_score": 0.61, "vote_rank": 2, "list": "fused", "id": "x"},
            {"section": "317", "title": "Stolen property", "score": 0.016, "statute_rank": 2, "vote_rank": None, "list": "text"}]
    st = {"case_facts": "f", "offence_date": "2024-08-15", "retrieved": rows, "unconfirmed": [], "withdrawn": [],
          "precedents": [], "defenses": []}
    out = report.build({"status": "ok", "era": "bns", "state": st, "charges": [], "doubted": [], "included": [],
                        "embedding_map": {"points": []}})
    assert out["retrieved"][0] == {"section": "303", "ref": "303(1)", "title": "Theft", "score": 0.0325,
                                   "statute_rank": 1, "statute_score": 0.61, "vote_rank": 2, "list": "fused"}
    assert "vote_rank" not in out["retrieved"][1]   # absent, not null
    assert out["embedding_map"] == {"points": []}


def test_pca_projection_is_scaled_and_keeps_order():
    rng = np.random.default_rng(0)
    v = rng.normal(size=(12, 32))
    coords, share = embedmap.project(v)
    assert coords.shape == (12, 2) and 0 < share <= 1
    assert np.abs(coords).max() == pytest.approx(1.0)


def test_embedding_map_never_breaks_a_run():
    assert embedmap.build("facts", "bns", [], {}, cli=object()) is None


@pytest.fixture
def client(monkeypatch):
    g = _graph()
    monkeypatch.setattr(main.graph, "citation_graph", lambda: g)
    return TestClient(main.app)


def test_graph_endpoints(client):
    r = client.get("/graph/bns/303")
    assert r.status_code == 200 and {n["id"] for n in r.json()["nodes"]} >= {"bns:303", "ipc:379"}
    assert client.get("/graph/bns/420").status_code == 404
    assert client.get("/graph/xyz/1").status_code == 404
    r = client.post("/graph", json={"era": "bns", "sections": ["303"], "doc_ids": ["doc2"]})
    assert any(n["role"] == "precedent" for n in r.json()["nodes"])
    assert client.post("/graph", json={"era": "x", "sections": []}).status_code == 422


def test_classic_page_is_kept(client):
    r = client.get("/classic")
    assert r.status_code == 200 and "Start a matter from its facts." in r.text


def test_stats_reads_saved_runs(client):
    s = client.get("/stats").json()
    assert {"corpus", "graph", "citation_check", "iltur", "samples", "model"} <= set(s)
    assert s["graph"]["judgments"] == 3 and s["graph"]["maps_to_edges"] == 2
    assert s["mapping"]["rows"] >= 575   # read from data/mappings, never hard-coded
    # the citation check holds on every saved evaluation run
    assert s["citation_check"]["total"]["leaked"] == 0
