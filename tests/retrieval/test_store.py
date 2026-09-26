"""Store and ranker logic, with the embedder replaced by a deterministic fake.

These pin behaviour, not model quality: model quality is the Phase 2 gate
(scripts/eval_retrieval.py), which needs the real index and the GPU.
"""
import hashlib

import chromadb
import pytest
from chromadb.config import Settings

from src.retrieval import embedder, ranker, store


def _fake_encode(texts, batch_size=32, device=None, **_):
    # Bag-of-words hashed into 64 dims, normalised: similar words -> similar
    # vectors, which is all these tests need.
    out = []
    for t in texts:
        v = [0.0] * 64
        for w in t.lower().split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
        n = sum(x * x for x in v) ** 0.5 or 1.0
        out.append([x / n for x in v])
    return out


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(embedder, "encode", _fake_encode)
    monkeypatch.setenv("EMBEDDING_MODEL", "fake/model")
    return chromadb.PersistentClient(path=str(tmp_path), settings=Settings(anonymized_telemetry=False))


def _statute(section, text, title="T", corpus="bns"):
    return {"chunk_id": f"{corpus}_s{section}", "doc_id": f"{corpus}_s{section}",
            "doc_type": "statute", "text": text, "source": "x", "court": None, "date": None,
            "sections_involved": [section], "corpus": corpus, "section": section,
            "section_title": title, "chapter": None, "chapter_title": None}


# --- metadata -----------------------------------------------------------------

def test_metadata_drops_none_and_empty_lists_keeps_real_lists():
    """Chroma 1.5 rejects None but accepts (and filters on) lists."""
    md = store.to_metadata({"court": None, "date": None, "sections_involved": ["303", "34"],
                            "title": "X v. Y", "para_index": 3})
    assert md == {"sections_involved": ["303", "34"], "title": "X v. Y", "para_index": 3}
    assert "sections_involved" not in store.to_metadata({"sections_involved": []})


# --- sub-section views --------------------------------------------------------

S3 = ("3. (1) Throughout this Sanhita every definition shall be understood subject to exceptions.\n"
      "(2) Every expression explained in any Part is used in the same sense.\n"
      "(5) When a criminal act is done by several persons in furtherance of the common "
      "intention of all, each of such persons is liable for that act.\n")


def test_multi_subsection_statute_gets_views_with_same_section():
    recs = list(store.records(_statute("3", S3, "General explanations"), statute=True))
    ids = [r[0] for r in recs]
    assert ids == ["bns_s3", "bns_s3#ss1", "bns_s3#ss2", "bns_s3#ss5"]
    assert all(r[2]["section"] == "3" for r in recs)
    ss5 = recs[-1]
    assert ss5[2]["subsection"] == "3(5)"
    assert "common intention" in ss5[1] and "Throughout" not in ss5[1]


def test_single_provision_statute_and_judgments_get_no_views():
    assert len(list(store.records(_statute("303", "303. (1) Whoever intending to take..."),
                                  statute=True))) == 1
    j = {"chunk_id": "j_p1", "text": "(1) x\n(2) y\n", "sections_involved": []}
    assert len(list(store.records(j, statute=False))) == 1


# --- build + retrieve ---------------------------------------------------------

def test_build_retrieve_sections_collapses_views(fake, monkeypatch):
    chunks = [_statute("3", S3, "General explanations"),
              _statute("303", "303. (1) Whoever dishonestly takes movable property commits theft.", "Theft")]
    monkeypatch.setattr(store, "iter_chunks", lambda c: iter(chunks))
    n = store.build("bns_sections", cli=fake)
    assert n == 1 + 3 + 1                       # s3 + 3 views + s303
    got = store.retrieve_sections("several persons in furtherance of the common intention",
                                  "bns_sections", top_k=2, cli=fake)
    assert [r["section"] for r in got][0] == "3"
    assert got[0]["matched"] == "3(5)" and got[0]["id"] == "bns_s3"
    assert len({r["section"] for r in got}) == len(got)      # one entry per section


def test_retrieve_refuses_a_collection_built_with_another_model(fake, monkeypatch):
    chunks = [_statute("303", "303. theft")]
    monkeypatch.setattr(store, "iter_chunks", lambda c: iter(chunks))
    store.build("bns_sections", cli=fake)
    monkeypatch.setenv("EMBEDDING_MODEL", "other/model")
    with pytest.raises(RuntimeError, match="querying across models"):
        store.retrieve("theft", "bns_sections", cli=fake)


def test_unknown_collection_and_empty_query_rejected(fake):
    with pytest.raises(ValueError):
        store.retrieve("x", "judgments_2099", cli=fake)
    with pytest.raises(ValueError):
        store.retrieve("   ", "bns_sections", cli=fake)


def test_section_filter_on_list_metadata(fake, monkeypatch):
    """Node 3's query shape: precedent for ONE section via $contains."""
    js = [{"chunk_id": f"j{i}_p0", "doc_id": f"j{i}", "text": t, "sections_involved": s}
          for i, (t, s) in enumerate([("theft of a motorcycle", ["379"]),
                                      ("theft of a car and cheating", ["379", "420"]),
                                      ("cheating by a builder", ["420"])])]
    monkeypatch.setattr(store, "iter_chunks", lambda c: iter(js))
    store.build("judgments_pre2024", cli=fake)
    got = store.retrieve("theft", "judgments_pre2024", top_k=5, cli=fake,
                         where={"sections_involved": {"$contains": "420"}})
    assert {h["id"] for h in got} == {"j1_p0", "j2_p0"}


# --- embedder guard -----------------------------------------------------------

@pytest.mark.parametrize("bad", ["law-ai/InLegalBERT", r"D:\legal\InLegalBERT"])
def test_base_inlegalbert_is_refused(monkeypatch, bad):
    monkeypatch.setenv("EMBEDDING_MODEL", bad)
    with pytest.raises(ValueError, match="not InLegal-Sbert"):
        embedder.model_id()


# --- precedent voting ---------------------------------------------------------

def _hit(secs, hint, doc="d1", score=0.8):
    return {"id": doc + "_p0", "score": score,
            "metadata": {"sections_involved": secs, "corpus_hint": hint, "doc_id": doc}}


def test_ipc_era_votes_only_from_ipc_judgments():
    assert ranker._sections_in_era(_hit(["379", "34"], "ipc"), "judgments_pre2024", "ipc") == ["379", "34"]
    # union-validated sections cannot be trusted to speak IPC numbering
    assert ranker._sections_in_era(_hit(["303"], "ipc,bns"), "judgments_pre2024", "ipc") == []


def test_bns_era_translates_ipc_votes_through_verified_mapping_only(monkeypatch):
    monkeypatch.setattr(ranker, "_ipc_to_bns", {"379": "303", "34": "3"})
    got = ranker._sections_in_era(_hit(["379", "34", "999"], "ipc"), "judgments_pre2024", "bns")
    assert got == ["3", "303"]                  # 999 has no verified row: no vote
    assert ranker._sections_in_era(_hit(["303"], "bns"), "judgments_post2024", "bns") == ["303"]
    assert ranker._sections_in_era(_hit(["303"], "ipc,bns"), "judgments_post2024", "bns") == []


def test_verified_mapping_excludes_none_rows():
    m = ranker.ipc_to_bns()
    assert m["379"] == "303" and m["420"] == "318" and m["34"] == "3"
    assert all(v for v in m.values())


def test_one_vote_per_judgment_not_per_chunk(monkeypatch):
    hits = [_hit(["379"], "ipc", "long", 0.9), _hit(["379"], "ipc", "long", 0.85),
            _hit(["379"], "ipc", "long", 0.8), _hit(["420"], "ipc", "other", 0.7)]
    for i, h in enumerate(hits):
        h["id"] = f"{h['metadata']['doc_id']}_p{i}"
    monkeypatch.setattr(store, "retrieve", lambda *a, **k: hits)
    votes = ranker.precedent_votes("q", "ipc")
    assert votes == {"379": 0.9, "420": 0.7}


def test_sync_metadata_updates_in_place_and_refuses_text_changes(fake, monkeypatch):
    js = [{"chunk_id": "j0_p0", "doc_id": "j0", "text": "theft of a motorcycle", "sections_involved": ["379"]}]
    monkeypatch.setattr(store, "iter_chunks", lambda c: iter(js))
    store.build("judgments_pre2024", cli=fake)
    js[0]["sections_involved"] = ["379", "304B"]          # new section ingested
    assert store.sync_metadata("judgments_pre2024", cli=fake) == 1
    got = store.retrieve("motorcycle", "judgments_pre2024", cli=fake)
    assert got[0]["metadata"]["sections_involved"] == ["379", "304B"]
    js[0]["text"] = "theft of a scooter"                   # text change -> stale vector
    with pytest.raises(RuntimeError, match="embeddings are stale"):
        store.sync_metadata("judgments_pre2024", cli=fake)
