r"""The four ChromaDB collections, and the one reusable retrieve().

CLAUDE.md Section 5 fixes the collections; Phase 2 asks for exactly one
`retrieve(query_text, collection) -> top_k` function that everything later
calls. Both live here.

    ipc_sections        <- data/processed/statutes_ipc.jsonl
    bns_sections        <- data/processed/statutes_bns.jsonl
    judgments_pre2024   <- data/processed/judgments_pre2024.jsonl   (IPC era)
    judgments_post2024  <- data/processed/judgments_post2024.jsonl  (BNS era)

Metadata
--------
ChromaDB 1.5 accepts list-valued metadata and filters on it with `$contains`,
so `sections_involved` is stored as the real list -- which is what lets Node 3
ask for precedent on one section:  where={"sections_involved": {"$contains":
"303"}}. It REJECTS None values, so absent fields are dropped, not nulled.

A collection remembers its embedder
-----------------------------------
Each collection records the model that embedded it. Querying it with any other
model returns confident nonsense rather than an error, so retrieve() refuses.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import embedder

ROOT = embedder.ROOT
PROCESSED = ROOT / "data" / "processed"

COLLECTIONS = {
    "ipc_sections": "statutes_ipc.jsonl",
    "bns_sections": "statutes_bns.jsonl",
    "judgments_pre2024": "judgments_pre2024.jsonl",
    "judgments_post2024": "judgments_post2024.jsonl",
}

# Metadata kept on each record. `text` is the document itself; everything else
# is either redundant or too large to be useful as a filter.
_META_FIELDS = (
    "doc_id", "doc_type", "source", "court", "date", "sections_involved",
    "corpus", "section", "section_title", "chapter", "chapter_title",
    "case_id", "citation", "title", "disposal_nature", "para_index",
    "is_headnote", "corpus_hint", "decision_year_min", "outcome_label",
)


def chroma_dir():
    raw = os.environ.get("CHROMA_DIR", "./chroma_db")
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


def client(path=None):
    import chromadb
    from chromadb.config import Settings

    return chromadb.PersistentClient(
        path=str(path or chroma_dir()),
        settings=Settings(anonymized_telemetry=False),
    )


def to_metadata(chunk):
    """Chunk -> Chroma metadata: scalars and non-empty lists only, no None."""
    md = {}
    for k in _META_FIELDS:
        v = chunk.get(k)
        if v is None:
            continue
        if isinstance(v, list):
            if not v:
                continue            # an empty list carries nothing to filter on
            v = [str(x) for x in v]
        md[k] = v
    return md


STATUTE_COLLECTIONS = {"ipc_sections", "bns_sections"}

# A sub-section opens a line: "(5) When a criminal act is done by several ...".
_SUBSECTION = re.compile(r"(?m)^[ \t]*(?:\d+[A-Z]*\.\s*)?\((\d+)\)\s")


MAPPING = ROOT / "data" / "mappings" / "ipc_bns_map.json"
_bns_views = None


def _ipc_counterpart_views():
    """{ipc section: [(bns ref, text)]} for IPC sections with a VERIFIED BNS row.

    The text is the BNS counterpart's gazette text -- the exact sub-section
    where the mapping names one (IPC 34 -> BNS 3(5)), else the whole section.
    """
    global _bns_views
    if _bns_views is None:
        bns = {c["section"]: c for c in iter_chunks("bns_sections")}
        entries = json.loads(MAPPING.read_text(encoding="utf-8"))["entries"]
        _bns_views = {}
        for ipc, e in entries.items():
            b = e.get("bns_section")
            if e.get("decision") == "none" or b not in bns:
                continue
            sub = e.get("bns_subsection")
            text = None
            if sub and sub != b:
                for _, vtext, md in records(bns[b], statute=True):
                    if md.get("subsection") == sub:
                        text = vtext
                        break
            _bns_views[ipc] = [(sub or b, text or bns[b]["text"])]
    return _bns_views


def records(chunk, statute):
    """The index records for one corpus chunk: (id, text, metadata).

    Judgments: one record per chunk. Statutes: the whole section, PLUS one
    record per sub-section when a section has two or more. BNS s3 is the case
    that forced this: it is a 4,765-char "General explanations" section, and
    common intention is its 194-char sub-section (5). Embedded whole, s3 ranked
    155th for a textbook common-intention query; the rule is drowned by eight
    unrelated neighbours. The corpus itself stays one-section-per-chunk
    (Section 8); only the index adds views, and every view carries the same
    `section`, so retrieve_sections() collapses them back to one section.
    """
    md = to_metadata(chunk)
    yield chunk["chunk_id"], chunk["text"], md
    if not statute:
        return
    if chunk.get("corpus") == "ipc":
        # IPC sections borrow their verified BNS counterpart's text as an extra
        # view. Why: the civictech IPC text is the bare provision with every
        # Illustration stripped, while the gazette BNS keeps them -- and
        # Illustrations ("A takes Z's ring out of Z's box...") are short fact
        # narratives, the very register case facts are written in. At the
        # Phase 2 gate all 7 BNS cases hit and all the misses were IPC. The
        # mapping was verified row by row, so the view describes the SAME
        # offence; the record returned is still the IPC section, and the BNS
        # text never leaves the index as if it were IPC text.
        for ref, text in _ipc_counterpart_views().get(chunk["section"], []):
            title = chunk.get("section_title") or ""
            yield (f"{chunk['chunk_id']}#bns{ref}",
                   f"{title}. {text}" if title else text,
                   {**md, "view": f"bns:{ref}"})
        return
    text = chunk["text"]
    marks = list(_SUBSECTION.finditer(text))
    if len(marks) < 2:
        return
    title = chunk.get("section_title") or ""
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.start():end].strip()
        sub = f"{chunk['section']}({m.group(1)})"
        view = f"{title}. Section {sub}. {body}" if title else f"Section {sub}. {body}"
        yield f"{chunk['chunk_id']}#ss{m.group(1)}", view, {**md, "subsection": sub}


def _check(collection):
    if collection not in COLLECTIONS:
        raise ValueError(f"unknown collection {collection!r}; one of {sorted(COLLECTIONS)}")


def iter_chunks(collection):
    path = PROCESSED / COLLECTIONS[collection]
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def build(collection, batch_size=256, encode_batch=16, device=None, cli=None, progress=None):
    """(Re)embed one collection from its JSONL. Returns the record count.

    Dropped and rebuilt whole rather than upserted: a stale record surviving a
    rebuild -- a chunk the corpus no longer contains -- is precisely a citation
    the corpus cannot back, and upsert would keep it.
    """
    _check(collection)
    cli = cli or client()
    if collection in {c.name for c in cli.list_collections()}:
        cli.delete_collection(collection)
    col = cli.create_collection(
        collection,
        configuration={"hnsw": {"space": "cosine"}},
        metadata={"embedding_model": embedder.model_id(), "source_file": COLLECTIONS[collection]},
    )

    n, ids, docs, metas = 0, [], [], []

    def flush():
        nonlocal n
        if not ids:
            return
        col.add(ids=list(ids), documents=list(docs), metadatas=list(metas),
                embeddings=embedder.encode(docs, batch_size=encode_batch, device=device))
        n += len(ids)
        if progress:
            progress(n)
        ids.clear(); docs.clear(); metas.clear()

    statute = collection in STATUTE_COLLECTIONS
    expected = 0
    for chunk in iter_chunks(collection):
        for rid, text, md in records(chunk, statute):
            ids.append(rid)
            docs.append(text)
            metas.append(md)
            expected += 1
        if len(ids) >= batch_size:
            flush()
    flush()

    # Count what is IN the store, not what this loop believes it added -- the
    # Phase 1 lesson (a count kept in memory proves nothing about storage).
    stored = col.count()
    if stored != expected:
        raise RuntimeError(f"{collection}: {stored} records stored, {expected} in the corpus")
    return stored


def _collection(collection, cli=None):
    _check(collection)
    cli = cli or client()
    col = cli.get_collection(collection)
    built_with = (col.metadata or {}).get("embedding_model")
    if built_with != embedder.model_id():
        raise RuntimeError(
            f"{collection} was embedded with {built_with!r} but EMBEDDING_MODEL is "
            f"{embedder.model_id()!r}; querying across models returns nonsense. "
            "Rebuild with scripts/build_index.py or fix EMBEDDING_MODEL.")
    return col


def retrieve(query_text, collection, top_k=5, where=None, device=None, cli=None):
    """Top-k records for `query_text` from one collection, best first.

    Returns a list of {"id", "text", "score", "metadata"} where score is cosine
    similarity (1.0 = identical direction). `where` is a Chroma metadata filter,
    e.g. {"sections_involved": {"$contains": "303"}}.

    One collection per call, by design: the offence-date router decides which
    code's collections a query may see, and nothing here second-guesses it.
    """
    if not query_text or not query_text.strip():
        raise ValueError("empty query")
    col = _collection(collection, cli)
    res = col.query(
        query_embeddings=embedder.encode([query_text], device=device),
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    out = []
    for i, doc, md, dist in zip(res["ids"][0], res["documents"][0],
                                res["metadatas"][0], res["distances"][0]):
        out.append({"id": i, "text": doc, "score": round(1.0 - dist, 4), "metadata": md})
    return out


def retrieve_sections(query_text, collection, top_k=5, device=None, cli=None, pool=None):
    """Top-k SECTIONS from a statute collection, one entry per section.

    A section can match through its whole-section record or any sub-section
    view; it scores as its best view, and `matched` says which one won (e.g.
    "3(5)"), which is what a report should show the lawyer.
    """
    if collection not in STATUTE_COLLECTIONS:
        raise ValueError(f"{collection!r} is not a statute collection")
    hits = retrieve(query_text, collection, top_k=pool or max(top_k * 6, 30),
                    device=device, cli=cli)
    best = {}
    for h in hits:
        sec = h["metadata"]["section"]
        if sec not in best or h["score"] > best[sec]["score"]:
            best[sec] = {
                "section": sec,
                "score": h["score"],
                "matched": h["metadata"].get("subsection", sec),
                "title": h["metadata"].get("section_title"),
                "id": h["id"].split("#")[0],
                "text": h["text"],
            }
    return sorted(best.values(), key=lambda r: -r["score"])[:top_k]


def sync_metadata(collection, cli=None, page=2000):
    """Refresh stored metadata from the corpus WITHOUT re-embedding.

    For corpus rebuilds that change only metadata -- e.g. a newly ingested
    statute section giving judgments a new entry in `sections_involved`. The
    record ids and texts must match the corpus exactly; if any differ, the
    embeddings are stale too and this refuses, because silently keeping a
    vector for text that no longer exists is how an index drifts from its
    corpus. Returns the number of records whose metadata changed.
    """
    col = _collection(collection, cli)
    statute = collection in STATUTE_COLLECTIONS
    want = {}
    for chunk in iter_chunks(collection):
        for rid, text, md in records(chunk, statute):
            want[rid] = (text, md)

    have = {}
    offset = 0
    while True:
        got = col.get(include=["documents", "metadatas"], limit=page, offset=offset)
        if not got["ids"]:
            break
        for rid, doc, md in zip(got["ids"], got["documents"], got["metadatas"]):
            have[rid] = (doc, md)
        offset += len(got["ids"])

    if set(have) != set(want):
        raise RuntimeError(f"{collection}: record ids differ from the corpus "
                           f"({len(set(want) - set(have))} missing, {len(set(have) - set(want))} "
                           "extra) -- rebuild with scripts/build_index.py")
    stale = [rid for rid in want if want[rid][0] != have[rid][0]]
    if stale:
        raise RuntimeError(f"{collection}: {len(stale)} record texts changed (e.g. {stale[0]}) "
                           "-- their embeddings are stale; rebuild with scripts/build_index.py")

    changed = [rid for rid in want if want[rid][1] != have[rid][1]]
    for rid in changed:
        if set(have[rid][1]) - set(want[rid][1]):
            # Chroma's update merges keys; it cannot be trusted to delete one.
            raise RuntimeError(f"{collection}: {rid} would lose a metadata key -- rebuild instead")
    for i in range(0, len(changed), page):
        ids = changed[i:i + page]
        col.update(ids=ids, metadatas=[want[r][1] for r in ids])
    return len(changed)
