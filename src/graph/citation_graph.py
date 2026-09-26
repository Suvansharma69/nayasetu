r"""The citation graph: the ONLY authority on whether a citation is real.

CLAUDE.md Section 2: every citation must be checked against this graph before
it is shown as verified -- a section number or case id is "real" only if it is
a node here, built from actually-ingested data. Node 2 of the pipeline calls
verify_section(); Node 3 calls get_precedents_for_section() and
get_ipc_predecessors(); the final verification pass calls both verify_*.

Nodes and edges
---------------
    section  "ipc:378", "bns:303"   one per ingested statute section
    case     "case:<doc_id>"        one per ingested judgment
    case  --cites-->  section       from the judgment's sections_involved
    ipc section --maps_to--> bns section   from the VERIFIED mapping only

Section node keys carry their CODE. There is deliberately no way to ask "is
302 a section?" without saying which code: IPC 302 is murder and BNS 302 is
something else entirely, and the union question is the error Known Gotchas
forbids. verify_section() requires the code.

Which code a judgment's citations belong to is its `corpus_hint`: "ipc" or
"bns" judgments get edges into that code. A judgment naming BOTH codes had its
sections validated against the union at ingest, so its bare numbers cannot be
attributed to either code; its edges come ONLY from citations that named their
code ("Section 303 of the BNS", `sections_attributed`). One with none becomes
a case node with no cites edges, and is counted, rather than guessed at.
"""
from __future__ import annotations

import json
import os
import pickle
import re
from collections import Counter
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
MAPPING = ROOT / "data" / "mappings" / "ipc_bns_map.json"
CODES = ("ipc", "bns")
STATUTE_FILES = {"ipc": "statutes_ipc.jsonl", "bns": "statutes_bns.jsonl"}
JUDGMENT_FILES = ("judgments_pre2024.jsonl", "judgments_post2024.jsonl")

# The same shape the schema accepts: 303, 304A, 376DA. Anything else is not a
# section number at all, whatever the graph holds.
_SECTION = re.compile(r"^\d{1,3}[A-Z]{0,3}$")


def graph_path():
    raw = os.environ.get("CITATION_GRAPH", "./citation_graph.gpickle")
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


def section_key(code, section):
    return f"{code}:{section}"


def case_key(doc_id):
    return f"case:{doc_id}"


def normalise(section):
    """'304-b' / ' 304B ' / 379 -> '304B' / '379'; None if not section-shaped."""
    if section is None:
        return None
    s = re.sub(r"[\s-]", "", str(section)).upper()
    return s if _SECTION.match(s) else None


def _jsonl(path):
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def build(processed=PROCESSED, mapping=MAPPING):
    """Build the graph from data/processed/ and the verified mapping."""
    g = nx.DiGraph()
    stats = Counter()

    for code, fname in STATUTE_FILES.items():
        for c in _jsonl(Path(processed) / fname):
            g.add_node(section_key(code, c["section"]), kind="section", code=code,
                       section=c["section"], title=c.get("section_title"),
                       chunk_id=c["chunk_id"], source=c.get("source"))
            stats[f"sections_{code}"] += 1

    cases = {}
    for fname in JUDGMENT_FILES:
        collection = fname[: -len(".jsonl")]
        for c in _jsonl(Path(processed) / fname):
            key = case_key(c["doc_id"])
            if key not in cases:
                cases[key] = {
                    "kind": "case", "doc_id": c["doc_id"], "collection": collection,
                    "court": c.get("court"), "date": c.get("date"),
                    "decision_year_min": c.get("decision_year_min"),
                    "case_id": c.get("case_id"), "citation": c.get("citation"),
                    "title": c.get("title"), "disposal_nature": c.get("disposal_nature"),
                    "outcome_label": c.get("outcome_label"), "source": c.get("source"),
                    "corpus_hint": c.get("corpus_hint"), "cites": Counter(),
                    "attributed": c.get("sections_attributed"),
                }
            cases[key]["cites"].update(c.get("sections_involved") or [])

    for key, attrs in cases.items():
        cites = attrs.pop("cites")
        attributed = attrs.pop("attributed")
        g.add_node(key, **attrs)
        stats["cases"] += 1
        hint = attrs["corpus_hint"]
        if hint in CODES:
            targets = [(hint, sec, n) for sec, n in cites.items()]
        else:
            # Names both codes: its bare numbers were validated against the
            # union at ingest and cannot be attributed. Only citations that
            # NAMED their code ("Section 303 of the BNS") become edges.
            targets = [(code, sec, cites.get(sec, 1))
                       for code, secs in (attributed or {}).items() for sec in secs]
            stats["cases_two_codes"] += 1
            if not targets:
                stats["cases_two_codes_without_edges"] += 1
        for code, sec, n_chunks in targets:
            skey = section_key(code, sec)
            if skey not in g:
                # Cannot happen if ingest validated correctly; if it does, the
                # edge is dropped rather than a phantom section node created.
                stats["dropped_edges_unknown_section"] += 1
                continue
            g.add_edge(key, skey, kind="cites", chunks=n_chunks)
            stats["cites_edges"] += 1

    entries = json.loads(Path(mapping).read_text(encoding="utf-8"))["entries"]
    for ipc, e in entries.items():
        if e.get("decision") == "none" or not e.get("bns_section"):
            continue
        a, b = section_key("ipc", ipc), section_key("bns", e["bns_section"])
        if a in g and b in g:
            g.add_edge(a, b, kind="maps_to", bns_subsection=e.get("bns_subsection"),
                       reviewer=e.get("reviewer"), decision=e.get("decision"))
            stats["maps_to_edges"] += 1
        else:
            stats["mapping_rows_with_missing_node"] += 1

    g.graph["stats"] = dict(stats)
    g.graph["case_index"] = _case_index(g)
    return g


def _case_index(g):
    """Alternative identifiers -> case node: neutral citation, SCR citation."""
    idx = {}
    for n, d in g.nodes(data=True):
        if d.get("kind") != "case":
            continue
        idx[d["doc_id"]] = n
        for k in ("case_id", "citation"):
            if d.get(k):
                idx[_norm_case_id(d[k])] = n
    return idx


def _norm_case_id(s):
    return re.sub(r"\s+", " ", str(s)).strip().upper()


def save(g, path=None):
    path = Path(path or graph_path())
    with path.open("wb") as fh:
        pickle.dump(g, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return path


def load(path=None):
    with Path(path or graph_path()).open("rb") as fh:
        return pickle.load(fh)


# --- the verification API -------------------------------------------------------

def verify_section(g, code, section):
    """True only if `section` is an ingested section of `code` ('ipc' | 'bns').

    No code, no answer: there is no union mode (see module docstring).
    """
    if code not in CODES:
        raise ValueError(f"code must be one of {CODES}, got {code!r} -- a section is "
                         "only real relative to a code")
    s = normalise(section)
    if s is None:
        return False
    d = g.nodes.get(section_key(code, s))
    return bool(d) and d.get("kind") == "section"


def verify_case(g, identifier):
    """True only if `identifier` names an ingested judgment.

    Accepts the corpus doc_id ("2024_10_108_125", "na_Madras_HC_2022_3142"), a
    neutral citation ("2024 INSC 735") or an SCR citation, exactly as ingested.
    """
    if not identifier or not str(identifier).strip():
        return False
    ident = str(identifier).strip()
    node = g.graph["case_index"].get(ident) or g.graph["case_index"].get(_norm_case_id(ident))
    return node is not None and g.nodes[node].get("kind") == "case"


def get_precedents_for_section(g, code, section, limit=None):
    """Judgments citing `code` `section`, most-cited first (by citing chunks).

    Returns [] for a section that does not verify -- precedent for a section
    that does not exist is not a thing to return.
    """
    if not verify_section(g, code, section):
        return []
    skey = section_key(code, normalise(section))
    out = []
    for case in g.predecessors(skey):
        e = g.edges[case, skey]
        if e.get("kind") != "cites":
            continue
        d = g.nodes[case]
        out.append({"case": case, "doc_id": d["doc_id"], "chunks": e["chunks"],
                    "court": d.get("court"), "date": d.get("date"),
                    "title": d.get("title"), "citation": d.get("citation"),
                    "case_id": d.get("case_id"), "collection": d.get("collection"),
                    "disposal_nature": d.get("disposal_nature"),
                    "outcome_label": d.get("outcome_label")})
    out.sort(key=lambda r: (-r["chunks"], r["doc_id"]))
    return out[:limit] if limit else out


def get_ipc_predecessors(g, bns_section):
    """IPC sections that map to `bns_section` under the VERIFIED mapping.

    Node 3's pre-transition precedent check: BNS 303 (theft) <- IPC 378, 379.
    """
    if not verify_section(g, "bns", bns_section):
        return []
    bkey = section_key("bns", normalise(bns_section))
    return sorted(g.nodes[p]["section"] for p in g.predecessors(bkey)
                  if g.edges[p, bkey].get("kind") == "maps_to")


def get_bns_successor(g, ipc_section):
    """The BNS section an IPC section maps to under the verified mapping, or None."""
    if not verify_section(g, "ipc", ipc_section):
        return None
    akey = section_key("ipc", normalise(ipc_section))
    for s in g.successors(akey):
        if g.edges[akey, s].get("kind") == "maps_to":
            return g.nodes[s]["section"]
    return None
