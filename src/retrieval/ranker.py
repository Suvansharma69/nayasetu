r"""Statute candidates for a case: direct statute retrieval + precedent votes.

Why two signals
---------------
Case facts are narrative ("four men arrived together, having agreed to teach
him a lesson..."); statutes are abstract definitions ("when a criminal act is
done by several persons in furtherance of the common intention of all...").
Embedding one against the other is the weak link: at the Phase 2 bake-off even
the better embedder put IPC s34 at rank 77 for a textbook common-intention
query. Judgments, though, are narrative too -- matching facts against
judgment chunks is fact-to-fact, which embedders are good at -- and every
judgment chunk carries the sections the court applied (`sections_involved`).
So similar judgments VOTE for their sections, and the vote is fused with the
direct statute ranking by reciprocal-rank fusion (RRF, k=60, equal weights --
the textbook default, not a value tuned on the 15 test cases).

What this does NOT change
-------------------------
* Every section returned is a section of the era's own code, from the ingested
  corpus. Votes arriving from IPC precedent for a BNS-era query are translated
  ONLY through the verified mapping (data/mappings/ipc_bns_map.json, never the
  unverified candidates file); an IPC section with no verified row casts no
  BNS vote. Node 2 still verifies everything against the citation graph.
* The router decides the era; nothing here looks at the other code's statutes.
"""
from __future__ import annotations

import json
from collections import defaultdict

from . import store

ERA = {
    "ipc": {"statutes": "ipc_sections", "judgments": ["judgments_pre2024"]},
    # BNS-era precedent is thin (28 SC judgments at 2026-09-26), so IPC
    # precedent votes too, through the verified mapping -- the same bridge
    # Node 3's IPC-predecessor check uses.
    "bns": {"statutes": "bns_sections", "judgments": ["judgments_post2024", "judgments_pre2024"]},
}
RRF_K = 60
MAPPING = store.ROOT / "data" / "mappings" / "ipc_bns_map.json"

_ipc_to_bns = None


def ipc_to_bns():
    """Verified IPC -> BNS section map. 'none' rows (no BNS equivalent) excluded."""
    global _ipc_to_bns
    if _ipc_to_bns is None:
        entries = json.loads(MAPPING.read_text(encoding="utf-8"))["entries"]
        _ipc_to_bns = {ipc: e["bns_section"] for ipc, e in entries.items()
                       if e.get("decision") != "none" and e.get("bns_section")}
    return _ipc_to_bns


def _sections_in_era(hit, collection, era):
    """The sections a judgment hit may vote for, in the era's numbering."""
    md = hit["metadata"]
    secs = md.get("sections_involved") or []
    hint = md.get("corpus_hint")
    if era == "ipc":
        # pre2024 is the IPC-era collection; a judgment naming both codes had
        # its sections validated against the union and cannot be trusted to
        # speak IPC numbering.
        return secs if hint == "ipc" else []
    if collection == "judgments_post2024":
        return secs if hint == "bns" else []
    if hint != "ipc":
        return []
    m = ipc_to_bns()
    return sorted({m[s] for s in secs if s in m})


def precedent_votes(query_text, era, pool=60, cli=None):
    """{section: vote} from the `pool` most similar judgment chunks.

    One vote per JUDGMENT, not per chunk: a long judgment whose paragraphs all
    resemble the query must not outvote five different courts.
    """
    best_per_doc = {}
    for collection in ERA[era]["judgments"]:
        for h in store.retrieve(query_text, collection, top_k=pool, cli=cli):
            secs = _sections_in_era(h, collection, era)
            if not secs:
                continue
            doc = h["metadata"].get("doc_id", h["id"])
            if doc not in best_per_doc or h["score"] > best_per_doc[doc][0]:
                best_per_doc[doc] = (h["score"], secs)
    votes = defaultdict(float)
    for score, secs in best_per_doc.values():
        for s in secs:
            votes[s] += score
    return dict(votes)


def rank_sections(query_text, era, top_k=5, pool=60, cli=None, use_votes=True):
    """Fused section ranking for one case. Returns a list, best first, of
    {section, score, statute_rank, vote_rank, title, matched, id}."""
    if era not in ERA:
        raise ValueError(f"era must be 'ipc' or 'bns', got {era!r}")
    cli = cli or store.client()
    statute = store.retrieve_sections(query_text, ERA[era]["statutes"],
                                      top_k=pool, cli=cli, pool=pool * 4)
    s_rank = {r["section"]: i + 1 for i, r in enumerate(statute)}
    info = {r["section"]: r for r in statute}

    v_rank = {}
    if use_votes:
        votes = precedent_votes(query_text, era, pool=pool, cli=cli)
        # A vote for a section the era's statute corpus does not contain
        # cannot happen through the paths above; guard anyway, because a
        # section that is not in the corpus must never be proposed.
        valid = _era_sections(era)
        ordered = sorted((s for s in votes if s in valid), key=lambda s: -votes[s])
        v_rank = {s: i + 1 for i, s in enumerate(ordered)}

    fused = {}
    for sec in set(s_rank) | set(v_rank):
        score = 0.0
        if sec in s_rank:
            score += 1.0 / (RRF_K + s_rank[sec])
        if sec in v_rank:
            score += 1.0 / (RRF_K + v_rank[sec])
        fused[sec] = score

    out = []
    for sec in sorted(fused, key=lambda s: -fused[s])[:top_k]:
        r = info.get(sec) or _section_record(era, sec)
        out.append({
            "section": sec,
            "score": round(fused[sec], 5),
            "statute_rank": s_rank.get(sec),
            "vote_rank": v_rank.get(sec),
            "title": r.get("title") if "title" in r else r.get("section_title"),
            "matched": r.get("matched", sec),
            "id": r.get("id", r.get("chunk_id")),
        })
    return out


_era_cache = {}


def _era_records(era):
    if era not in _era_cache:
        _era_cache[era] = {c["section"]: c for c in store.iter_chunks(ERA[era]["statutes"])}
    return _era_cache[era]


def _era_sections(era):
    return set(_era_records(era))


def _section_record(era, sec):
    return _era_records(era)[sec]
