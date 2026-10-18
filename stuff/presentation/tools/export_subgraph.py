"""Export the REAL citation-graph neighbourhood of theft for the deck's graph animations.

Writes stuff/presentation/data/subgraph.js (a JS global, so the deck works from file://
without fetch). Every node and edge comes from the built graph; cases are a
deterministic sample where a section has more than the cap.

    venv\\Scripts\\python.exe stuff\\presentation\\tools\\export_subgraph.py
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.graph import citation_graph as cg  # noqa: E402

SECTIONS = ["bns:303", "bns:317", "ipc:378", "ipc:379", "ipc:411"]
CAP = {"ipc:378": 11, "ipc:379": 34, "ipc:411": 18}


def stable(s):
    return hashlib.md5(s.encode()).hexdigest()


def main():
    g = cg.load()
    nodes, edges, cases = {}, [], set()
    for s in SECTIONS:
        d = g.nodes[s]
        nodes[s] = {"id": s, "kind": "section", "code": d["code"], "section": d["section"],
                    "title": d["title"], "cited_by": sum(1 for u, _, e in g.in_edges(s, data=True)
                                                         if e.get("kind") == "cites")}
    for s, cap in CAP.items():
        citing = [u for u, _, e in g.in_edges(s, data=True) if e.get("kind") == "cites"]
        # prefer cases that also cite another section of the subgraph, then a stable hash order
        citing.sort(key=lambda u: (-sum(g.has_edge(u, t) for t in SECTIONS), stable(u)))
        cases.update(citing[:cap])
    for c in sorted(cases):
        d = g.nodes[c]
        nodes[c] = {"id": c, "kind": "case", "court": d.get("court") or "", "year": (d.get("date") or "")[:4]}
        for s in SECTIONS:
            if g.has_edge(c, s):
                edges.append({"from": c, "to": s, "kind": "cites"})
    for u in SECTIONS:
        for v in SECTIONS:
            if g.has_edge(u, v) and g.edges[u, v].get("kind") == "maps_to":
                edges.append({"from": u, "to": v, "kind": "maps_to"})
    out = {"note": "Real subgraph of data/processed citation_graph.gpickle; cases sampled deterministically.",
           "totals": {"sections": sum(1 for _, d in g.nodes(data=True) if d.get("kind") == "section"),
                      "cases": sum(1 for _, d in g.nodes(data=True) if d.get("kind") == "case"),
                      "cites": sum(1 for *_, d in g.edges(data=True) if d.get("kind") == "cites"),
                      "maps_to": sum(1 for *_, d in g.edges(data=True) if d.get("kind") == "maps_to")},
           "nodes": list(nodes.values()), "edges": edges}
    dest = ROOT / "stuff" / "presentation" / "data" / "subgraph.js"
    dest.write_text("window.SUBGRAPH = " + json.dumps(out, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(dest, len(nodes), "nodes", len(edges), "edges", out["totals"])


if __name__ == "__main__":
    main()
