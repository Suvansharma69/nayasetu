r"""Node 3: precedent matcher.

A judgment is precedent for a charge only if the citation graph has an edge
from it to that section (the same audited edges Node 2 trusts); similarity
decides the ORDER, never membership. For a BNS charge, the verified IPC
predecessor's judgments are searched too (CLAUDE.md Section 3): BNS 303 has no
reported appeal yet, while IPC 378/379 have hundreds.

The VRAM handoff (CLAUDE.md Section 2): BGE-M3 and qwen3.5:4b cannot share the
card, and Node 3 runs after Node 1 has loaded the LLM. So the judgment
neighbourhood of the facts is fetched once, BEFORE generation, while the
embedder is still on the card (`prefetch`), and Node 3 only filters it.
"""
from __future__ import annotations

import re

from src.graph import citation_graph as cg
from src.retrieval import ranker, store

from .applicability import charged as _charged

POOL_PER_COLLECTION = 200
PER_CHARGE = 3
EXCERPT_CHARS = 500


def prefetch(case_facts, era, cli=None, device=None, top_k=POOL_PER_COLLECTION):
    """{doc_id: {"score", "chunk_id", "text"}} -- the best-matching chunk of each
    judgment near the facts, across the era's judgment collections."""
    pool = {}
    for collection in ranker.ERA[era]["judgments"]:
        for h in store.retrieve(case_facts, collection, top_k=top_k, cli=cli, device=device):
            doc = h["metadata"].get("doc_id", h["id"])
            if doc not in pool or h["score"] > pool[doc]["score"]:
                pool[doc] = {"score": h["score"], "chunk_id": h["id"], "text": h["text"]}
    return pool


def _excerpt(text):
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= EXCERPT_CHARS else t[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " ..."


def _for_section(g, code, section, pool, via=None):
    rows = []
    for p in cg.get_precedents_for_section(g, code, section):
        hit = pool.get(p["doc_id"])
        rows.append({**p, "applies": f"{code.upper()} {section}", "via_ipc_predecessor": via,
                     "similarity": hit["score"] if hit else None,
                     "excerpt": _excerpt(hit["text"]) if hit else None,
                     "matched_by": "similarity to the facts" if hit else "most cited"})
    # Similar-to-the-facts first; among those not in the neighbourhood, most cited.
    rows.sort(key=lambda r: (r["similarity"] is None, -(r["similarity"] or 0), -r["chunks"]))
    return rows


def precedent_matcher(state, g):
    """Node 3. {"precedents": [...]} -- up to PER_CHARGE per verified section,
    each verified as an ingested judgment."""
    era, pool = state["era"], state.get("precedent_pool") or {}
    out, used, texts = [], set(), set()
    for v in _charged(state):
        rows = _for_section(g, era, v["section"], pool)
        if era == "bns":
            for ipc in cg.get_ipc_predecessors(g, v["section"]):
                rows += _for_section(g, "ipc", ipc, pool, via=f"BNS {v['section']} <- IPC {ipc}")
            rows.sort(key=lambda r: (r["similarity"] is None, -(r["similarity"] or 0), -r["chunks"]))
        picked = 0
        for r in rows:
            # Companion appeals decided together are filed as separate
            # judgments with identical text; show one.
            key = (r["excerpt"] or "")[:200]
            if r["doc_id"] in used or (key and key in texts):
                continue
            if not cg.verify_case(g, r["doc_id"]):  # cannot fail for a graph edge; checked anyway
                continue
            used.add(r["doc_id"])
            texts.add(key)
            out.append({**r, "for_charge": f"{era.upper()} {v['section']}", "verified": True})
            picked += 1
            if picked == PER_CHARGE:
                break
    for i, p in enumerate(out, 1):
        p["label"] = f"P{i}"
    return {"precedents": out}
