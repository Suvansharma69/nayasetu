"""Citation graph: unit behaviour on a small synthetic corpus, then the Phase 3
gate on the REAL graph (skipped only if data/processed/ has not been built)."""
import json
from pathlib import Path

import pytest

from src.graph import citation_graph as cg

ROOT = Path(__file__).resolve().parents[2]


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _statute(code, sec, title):
    return {"chunk_id": f"{code}_s{sec}", "section": sec, "section_title": title,
            "corpus": code, "source": "x"}


def _judgment(doc, secs, hint, **kw):
    return {"chunk_id": f"{doc}_p0", "doc_id": doc, "sections_involved": secs,
            "corpus_hint": hint, "court": "Supreme Court of India", "date": "2023-05-01",
            "case_id": kw.get("case_id"), "citation": kw.get("citation"), "title": doc,
            "disposal_nature": "Dismissed"}


@pytest.fixture
def g(tmp_path):
    _write(tmp_path / "statutes_ipc.jsonl", [_statute("ipc", "302", "Murder"),
                                             _statute("ipc", "378", "Theft"),
                                             _statute("ipc", "379", "Punishment for theft"),
                                             _statute("ipc", "34", "Common intention")])
    _write(tmp_path / "statutes_bns.jsonl", [_statute("bns", "302", "Uttering words"),
                                             _statute("bns", "303", "Theft"),
                                             _statute("bns", "3", "General explanations")])
    _write(tmp_path / "judgments_pre2024.jsonl", [
        _judgment("a", ["379", "34"], "ipc", case_id="2023 INSC 10"),
        {**_judgment("a", ["379"], "ipc"), "chunk_id": "a_p1"},
        _judgment("b", ["379"], "ipc", citation="[2023] 5 S.C.R. 1"),
        _judgment("c", ["302"], "ipc")])
    _write(tmp_path / "judgments_post2024.jsonl", [
        _judgment("d", ["303"], "bns"),
        _judgment("e", ["302", "303"], "ipc,bns"),
        {**_judgment("f", ["302", "303", "379"], "ipc,bns"),
         "sections_attributed": {"ipc": ["379"], "bns": ["303"]}}])
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"entries": {
        "378": {"bns_section": "303", "decision": "confirmed"},
        "379": {"bns_section": "303", "decision": "corrected"},
        "34": {"bns_section": "3", "decision": "confirmed"}}}), encoding="utf-8")
    return cg.build(tmp_path, mapping)


def test_section_is_real_only_relative_to_its_code(g):
    assert cg.verify_section(g, "ipc", "302") and cg.verify_section(g, "bns", "302")
    assert cg.verify_section(g, "bns", "303") and not cg.verify_section(g, "ipc", "303")


def test_no_union_mode(g):
    with pytest.raises(ValueError, match="only real relative to a code"):
        cg.verify_section(g, None, "302")
    with pytest.raises(ValueError):
        cg.verify_section(g, "both", "302")


@pytest.mark.parametrize("raw", ["379", " 379 ", 379])
def test_section_normalised(g, raw):
    assert cg.verify_section(g, "ipc", raw)


@pytest.mark.parametrize("raw", ["", None, "379(2)", "s.379", "302.5", "3790"])
def test_non_section_shapes_never_verify(g, raw):
    assert not cg.verify_section(g, "ipc", raw)


def test_precedents_most_cited_first_and_empty_for_fakes(g):
    got = cg.get_precedents_for_section(g, "ipc", "379")
    assert [p["doc_id"] for p in got] == ["a", "b", "f"]       # a cites it in 2 chunks
    assert got[0]["chunks"] == 2
    assert cg.get_precedents_for_section(g, "ipc", "999") == []
    assert cg.get_precedents_for_section(g, "bns", "379") == []


def test_two_code_judgment_without_named_citations_gets_no_edges(g):
    """'e' names both codes; its '302' could be IPC murder or BNS s302."""
    assert cg.verify_case(g, "e")
    assert list(g.successors("case:e")) == []
    assert g.graph["stats"]["cases_two_codes_without_edges"] == 1
    assert "e" not in {p["doc_id"] for p in cg.get_precedents_for_section(g, "bns", "303")}


def test_two_code_judgment_gets_edges_only_from_named_citations(g):
    """'f' cited 'Section 379 IPC' and 'Section 303 of the BNS' by name, and a
    bare '302' that stays unattributed."""
    assert set(g.successors("case:f")) == {"ipc:379", "bns:303"}
    assert "f" in {p["doc_id"] for p in cg.get_precedents_for_section(g, "bns", "303")}


def test_ipc_predecessors_through_verified_mapping(g):
    assert cg.get_ipc_predecessors(g, "303") == ["378", "379"]
    assert cg.get_bns_successor(g, "34") == "3"
    assert cg.get_bns_successor(g, "302") is None           # no verified row
    assert cg.get_ipc_predecessors(g, "999") == []


def test_verify_case_by_any_ingested_identifier(g):
    assert cg.verify_case(g, "a")
    assert cg.verify_case(g, "2023 INSC 10")
    assert cg.verify_case(g, "2023  insc 10")               # whitespace/case tolerant
    assert cg.verify_case(g, "[2023] 5 S.C.R. 1")
    assert not cg.verify_case(g, "2023 INSC 11")
    assert not cg.verify_case(g, "")
    assert not cg.verify_case(g, None)


def test_save_load_roundtrip(g, tmp_path):
    p = cg.save(g, tmp_path / "g.gpickle")
    g2 = cg.load(p)
    assert cg.verify_section(g2, "bns", "303") and cg.verify_case(g2, "2023 INSC 10")


# --- the Phase 3 gate on the real graph -----------------------------------------

REAL_DATA = all((ROOT / "data" / "processed" / f).exists()
                for f in ("statutes_ipc.jsonl", "statutes_bns.jsonl") + cg.JUDGMENT_FILES)
ADVERSARIAL = json.loads((ROOT / "tests" / "fixtures" / "phase3_adversarial.json")
                         .read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real_graph():
    if not REAL_DATA:
        pytest.skip("data/processed/ not built")
    return cg.build()


@pytest.mark.parametrize("code,section", ADVERSARIAL["real"])
def test_gate_real_sections_verify(real_graph, code, section):
    assert cg.verify_section(real_graph, code, section)


@pytest.mark.parametrize("code,section", ADVERSARIAL["fabricated"])
def test_gate_fabricated_sections_rejected(real_graph, code, section):
    assert not cg.verify_section(real_graph, code, section)


def test_gate_worked_example_bridge(real_graph):
    """Section 3's worked example: BNS 303 verifies, and its IPC predecessors
    (theft 378/379) are reachable for Node 3's pre-transition precedent."""
    assert cg.verify_section(real_graph, "bns", "303")
    assert {"378", "379"} <= set(cg.get_ipc_predecessors(real_graph, "303"))
    assert len(cg.get_precedents_for_section(real_graph, "ipc", "379")) >= 5
