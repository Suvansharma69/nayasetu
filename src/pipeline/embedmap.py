r"""A 2-D picture of the retrieval step: where the case facts sit among the
statute sections and judgment passages the search found.

Every point is a real BGE-M3 vector: the query is encoded once more (the model
is still on the card at this moment -- this runs inside the retrieval stage,
before the VRAM handoff to Ollama), and the candidates' vectors are read back
from ChromaDB as indexed. The 1024-d vectors are projected to 2-D with PCA, so
the picture shows rough neighbourhoods only; the cosine to the facts that each
point carries is exact.

Never raises into the pipeline: the map is a view, and a run must not fail
because a view could not be drawn.
"""
from __future__ import annotations

import numpy as np

from src.retrieval import embedder, ranker, store

MAX_STATUTES = 18
MAX_JUDGMENTS = 30


def _vectors(cli, collection, ids):
    """{id: vector} for the ids present in `collection`."""
    if not ids:
        return {}
    col = cli.get_collection(collection)
    got = col.get(ids=list(ids), include=["embeddings"])
    embs = got.get("embeddings")
    if embs is None:
        return {}
    return {i: np.asarray(e, dtype=np.float32) for i, e in zip(got["ids"], embs)}


def project(vectors):
    """PCA to 2-D. -> (coords [n, 2], explained share of the two axes)."""
    X = np.asarray(vectors, dtype=np.float64)
    Xc = X - X.mean(axis=0)
    _, s, vt = np.linalg.svd(Xc, full_matrices=False)
    coords = Xc @ vt[:2].T
    var = s ** 2
    share = float(var[:2].sum() / var.sum()) if var.sum() > 0 else 0.0
    span = np.abs(coords).max() or 1.0
    return coords / span, share


def build(case_facts, era, retrieved, pool, cli=None, device=None):
    """{points: [...], explained, model} or None if it could not be built."""
    try:
        cli = cli or store.client()
        q = np.asarray(embedder.encode([case_facts], device=device)[0], dtype=np.float32)

        stat_rows = [r for r in retrieved if r.get("id")][:MAX_STATUTES]
        svec = _vectors(cli, ranker.ERA[era]["statutes"], [r["id"] for r in stat_rows])

        top = sorted(pool.items(), key=lambda kv: -kv[1]["score"])[:MAX_JUDGMENTS]
        jvec = {}
        for collection in ranker.ERA[era]["judgments"]:
            want = [v["chunk_id"] for _, v in top if v["chunk_id"] not in jvec]
            jvec.update(_vectors(cli, collection, want))

        points = [{"kind": "query", "label": "These facts", "cos": 1.0}]
        vecs = [q]
        for rank, r in enumerate(stat_rows, 1):
            v = svec.get(r["id"])
            if v is None:
                continue
            points.append({"kind": "statute", "section": r["section"], "label": f"{era.upper()} {r.get('matched') or r['section']}",
                           "title": r.get("title"), "rank": rank, "cos": round(float(v @ q), 4)})
            vecs.append(v)
        for doc, v in top:
            vec = jvec.get(v["chunk_id"])
            if vec is None:
                continue
            points.append({"kind": "judgment", "doc_id": doc, "label": doc, "cos": round(float(vec @ q), 4)})
            vecs.append(vec)
        if len(vecs) < 4:
            return None
        coords, share = project(vecs)
        for p, (x, y) in zip(points, coords):
            p["x"], p["y"] = round(float(x), 4), round(float(y), 4)
        return {"points": points, "explained": round(share, 3), "model": embedder.model_id(),
                "dims": int(q.shape[0])}
    except Exception:  # noqa: BLE001 -- a view; the run goes on without it
        return None
