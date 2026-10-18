r"""Read-only data for the web interface's graphs and its System view.

Everything is read from what the project built or measured, never generated:

* `neighbourhood()` is a sub-graph of the real citation graph (NetworkX,
  scripts/build_graph.py): section nodes, the verified IPC <-> BNS `maps_to`
  edges, judgment nodes with their `cites` edges (weight = citing chunks), and
  co-cited sections (other sections cited by the same judgments, counted).
* `stats()` reads the build report, the graph's own counts, the IL-TUR
  summaries and every saved evaluation run, and counts citations proposed,
  rejected by the graph and leaked into charges across those runs.
"""
from __future__ import annotations

import ast
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from src.graph import citation_graph as cg

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
BUILD_REPORT = ROOT / "data" / "processed" / "build_report.json"
SAMPLES = ROOT / "app" / "samples"
MAPPING = ROOT / "data" / "mappings" / "ipc_bns_map.json"
# Saved evaluation runs whose records carry candidates / verified / unconfirmed /
# charges, so the citation check can be counted from them directly.
RUN_FILES = {
    "IL-TUR LSI test (100 docs)": "iltur_lsi_test_100.jsonl",
    "IL-TUR LSI dev (100 docs)": "iltur_lsi_dev_100.jsonl",
    "External court orders (Phase 6)": "phase6_pipeline_runs.jsonl",
    "Fresh orders, intake on": "phase6_fresh_intake_on_runs.jsonl",
    "Retrieval withheld (stress)": "phase6_stress_runs.jsonl",
}
CODES = ("ipc", "bns")


def _year(d):
    if d.get("date"):
        return str(d["date"])[:4]
    if d.get("decision_year_min"):
        return f"{d['decision_year_min']}+"
    return None


def _case_label(d):
    title = d.get("title")
    if title:
        return title if len(title) <= 60 else title[:58].rsplit(" ", 1)[0] + "..."
    court = (d.get("court") or "Judgment").replace(" High Court", " HC")
    y = _year(d)
    return f"{court}{', ' + y if y else ''}"


def _section_node(g, key, role):
    d = g.nodes[key]
    return {"id": key, "kind": "section", "code": d["code"], "section": d["section"],
            "title": d.get("title"), "label": f"{d['code'].upper()} {d['section']}", "role": role,
            "cited_by": sum(1 for p in g.predecessors(key) if g.edges[p, key].get("kind") == "cites")}


def _case_node(g, key, role):
    d = g.nodes[key]
    return {"id": key, "kind": "case", "doc_id": d["doc_id"], "label": _case_label(d), "title": d.get("title"),
            "court": d.get("court"), "year": _year(d), "disposal": d.get("disposal_nature"), "role": role,
            "collection": d.get("collection")}


def _citing(g, skey):
    return [p for p in g.predecessors(skey) if g.edges[p, skey].get("kind") == "cites"]


def _counterparts(g, skey):
    out = [p for p in g.predecessors(skey) if g.edges[p, skey].get("kind") == "maps_to"]
    out += [s for s in g.successors(skey) if g.edges[skey, s].get("kind") == "maps_to"]
    return out


def neighbourhood(g, code, sections, doc_ids=(), per_section=6, cocited=4):
    """{nodes, edges, stats} around `sections` of `code`. Unknown sections are
    skipped (a section is shown only if it is a node of that code's graph)."""
    if code not in CODES:
        raise ValueError(f"code must be one of {CODES}")
    nodes, edges = {}, []
    seen_edges = set()

    def add_node(n):
        if n["id"] not in nodes:
            nodes[n["id"]] = n
        return nodes[n["id"]]

    def add_edge(a, b, kind, weight=1):
        k = (a, b, kind)
        if k not in seen_edges:
            seen_edges.add(k)
            edges.append({"source": a, "target": b, "kind": kind, "weight": weight})

    charges = []
    for s in sections:
        if not cg.verify_section(g, code, s):
            continue
        key = cg.section_key(code, cg.normalise(s))
        add_node(_section_node(g, key, "charge"))
        charges.append(key)

    # 1. the verified IPC <-> BNS bridge
    hubs = list(charges)
    for key in charges:
        for cp in _counterparts(g, key):
            add_node(_section_node(g, cp, "counterpart"))
            a, b = (cp, key) if g.nodes[cp]["code"] == "ipc" else (key, cp)
            add_edge(a, b, "maps_to")
            hubs.append(cp)

    # 2. judgments: the report's own precedents first, then the most-cited
    wanted = [cg.case_key(d) for d in doc_ids if cg.case_key(d) in g]
    for ck in wanted:
        add_node(_case_node(g, ck, "precedent"))
        for skey in hubs:
            if g.has_edge(ck, skey):
                add_edge(ck, skey, "cites", g.edges[ck, skey].get("chunks", 1))
    for skey in hubs:
        ranked = sorted(_citing(g, skey), key=lambda p: (-g.edges[p, skey].get("chunks", 1), p))
        for ck in ranked[:per_section]:
            add_node(_case_node(g, ck, "precedent" if ck in wanted else "cited"))
            add_edge(ck, skey, "cites", g.edges[ck, skey].get("chunks", 1))

    # 3. sections the same judgments also cite
    for skey in hubs:
        citing = _citing(g, skey)
        if not citing:
            continue
        co = Counter()
        for ck in citing:
            for t in g.successors(ck):
                if t != skey and t not in hubs and g.edges[ck, t].get("kind") == "cites" and g.nodes[t]["code"] == g.nodes[skey]["code"]:
                    co[t] += 1
        for t, n in co.most_common(cocited):
            add_node(_section_node(g, t, "cocited"))
            add_edge(skey, t, "co_cited", n)

    by_kind = Counter(e["kind"] for e in edges)
    return {"nodes": list(nodes.values()), "edges": edges,
            "stats": {"sections": sum(1 for n in nodes.values() if n["kind"] == "section"),
                      "judgments": sum(1 for n in nodes.values() if n["kind"] == "case"),
                      "edges": dict(by_kind)}}


# --- System view -----------------------------------------------------------------

def _jsonl(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _as_list(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.startswith("["):
        try:
            return list(ast.literal_eval(v))
        except (ValueError, SyntaxError):
            return []
    return []


def _section_of(v):
    return v.get("section") if isinstance(v, dict) else v


def citation_check(records):
    """Counts over saved runs: proposals, graph rejections, and charges that are
    NOT among the run's verified sections (leaked; must be 0)."""
    last = {}
    for r in records:
        last[r.get("id")] = r            # a re-run of an errored document replaces it
    runs = props = rejected = leaked = with_rej = 0
    for r in last.values():
        if str(r.get("status", "")).startswith("error"):
            continue
        runs += 1
        cands, unconf = _as_list(r.get("candidates")), _as_list(r.get("unconfirmed"))
        verified = {_section_of(v) for v in _as_list(r.get("verified"))}
        props += len(cands)
        rejected += len(unconf)
        with_rej += bool(unconf)
        leaked += sum(1 for c in _as_list(r.get("charges")) if _section_of(c) not in verified)
    return {"runs": runs, "proposals": props, "rejected": rejected, "runs_with_rejection": with_rej,
            "leaked": leaked}


def _iltur(split):
    p = DOCS / f"iltur_lsi_{split}_100_summary.json"
    if not p.exists():
        return None
    s = json.loads(p.read_text(encoding="utf-8"))
    ch = s["charges"]
    out = {"split": split, "n": s.get("n"), "errors": s.get("errors"),
           "macro_f1_all": round(ch["macro_f1_all"] * 100, 1),
           "macro_f1_supported": round(ch["macro_f1_supported"] * 100, 1),
           "ci95": [round(x * 100, 1) for x in ch.get("macro_f1_supported_ci95", [])],
           "micro": {k: round(ch[f"micro_{k}"] * 100, 1) for k in ("precision", "recall", "f1")},
           "published": s.get("published_best_macro_f1", {})}
    recs = _jsonl(DOCS / f"iltur_lsi_{split}_100.jsonl")
    support = Counter()
    seen = {}
    for r in recs:
        seen[r.get("id")] = r
    for r in seen.values():
        support.update(_as_list(r.get("gold")))
    f1 = ch.get("per_label_f1", {})
    out["labels"] = [{"label": lab.replace("Section ", ""), "support": n, "f1": round(f1.get(lab, 0.0) * 100, 1)}
                     for lab, n in support.most_common(14)]
    return out


def _mapping_counts():
    """Rows of the reviewed IPC -> BNS mapping, read from the file itself."""
    if not MAPPING.exists():
        return {"rows": 0, "no_successor": 0}
    entries = json.loads(MAPPING.read_text(encoding="utf-8"))["entries"]
    return {"rows": len(entries), "no_successor": sum(1 for e in entries.values() if e.get("decision") == "none")}


@lru_cache(maxsize=1)
def stats(g):
    rep = json.loads(BUILD_REPORT.read_text(encoding="utf-8")) if BUILD_REPORT.exists() else {}
    kinds = Counter()
    for _, d in g.nodes(data=True):
        kinds[d.get("kind") if d.get("kind") != "section" else f"section_{d.get('code')}"] += 1
    ekinds = Counter(d.get("kind") for _, _, d in g.edges(data=True))
    js = rep.get("judgment_stats", {})
    ny = (rep.get("nyaya") or {}).get("stats", {})
    sc_judgments = sum(v for k, v in js.items() if k.startswith("judgments_20"))
    runs = []
    for name, fname in RUN_FILES.items():
        recs = _jsonl(DOCS / fname)
        if recs:
            runs.append({"name": name, **citation_check(recs)})
    tot = {k: sum(r[k] for r in runs) for k in ("runs", "proposals", "rejected", "leaked")}
    cases = json.loads((SAMPLES / "cases.json").read_text(encoding="utf-8")) if (SAMPLES / "cases.json").exists() else []
    return {
        "corpus": {"ipc_sections": rep.get("statutes_ipc"), "bns_sections": rep.get("statutes_bns"),
                   "chunks_ipc_era": rep.get("judgments_pre2024"), "chunks_bns_era": rep.get("judgments_post2024"),
                   "sc_judgments_read": sc_judgments, "sc_judgments_kept": js.get("with_sections"),
                   "hc_rows_screened": ny.get("rows_read"), "hc_judgments_kept": ny.get("kept"),
                   "sc_by_year": {k[-4:]: v for k, v in sorted(js.items()) if k.startswith("judgments_20")},
                   "nyaya_families": (rep.get("nyaya") or {}).get("offence_families", {})},
        "graph": {"nodes": g.number_of_nodes(), "edges": g.number_of_edges(),
                  "ipc_sections": kinds.get("section_ipc", 0), "bns_sections": kinds.get("section_bns", 0),
                  "judgments": kinds.get("case", 0), "cites_edges": ekinds.get("cites", 0),
                  "maps_to_edges": ekinds.get("maps_to", 0)},
        "citation_check": {"by_set": runs, "total": tot},
        "iltur": [x for x in (_iltur("test"), _iltur("dev")) if x],
        "mapping": _mapping_counts(),
        "samples": len(cases),
    }
