r"""Add the retrieval signals and the embedding map to the saved sample reports.

Samples saved before 2026-10-18 keep the ranked candidate list but not the
scores that ranked it, nor the embedding map (src/pipeline/embedmap.py). Both
come from the retrieval step only -- no language model -- which is
deterministic, so this re-runs retrieval for each sample's facts and adds:

* to each `retrieved` row: score, statute_rank, statute_score, vote_rank, list;
* `embedding_map`.

Only if the re-run ranks EXACTLY the sections the saved report holds, in the
same order. Otherwise the sample is left untouched and reported: a score must
belong to the list it is shown beside.

Run with Ollama unloaded (it needs the GPU for BGE-M3):
    venv\Scripts\python.exe scripts\augment_samples.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api.report import RANK_KEYS, RETRIEVED_KEPT  # noqa: E402
from src.pipeline import embedmap, graph, llm, precedents  # noqa: E402
from src.retrieval import embedder, store  # noqa: E402

SAMPLES = ROOT / "app" / "samples"


def augment(path, cli, device):
    rep = json.loads(path.read_text(encoding="utf-8"))
    if rep.get("status") == "straddles_transition" or not rep.get("retrieved"):
        return "skipped: no single candidate list"
    facts = (rep.get("intake") or {}).get("facts") or rep["facts"]
    era = rep["era"]
    rows = graph.retrieve_candidates(facts, era, cli=cli, device=device)
    saved = [r["section"] for r in rep["retrieved"]]
    fresh = [r["section"] for r in rows[:RETRIEVED_KEPT]]
    if saved != fresh:
        return f"UNCHANGED: re-run ranks differ\n  saved {saved}\n  fresh {fresh}"
    for r, f in zip(rep["retrieved"], rows):
        r.update({k: f[k] for k in RANK_KEYS if f.get(k) is not None})
    pool = precedents.prefetch(facts, era, cli=cli, device=device)
    rep["embedding_map"] = embedmap.build(facts, era, rows, pool, cli=cli, device=device)
    path.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    n = len((rep["embedding_map"] or {}).get("points", []))
    return f"added scores to {len(saved)} candidates and a {n}-point embedding map"


def main():
    llm.unload()
    device = "cuda"
    cli = store.client()
    cases = json.loads((SAMPLES / "cases.json").read_text(encoding="utf-8"))
    for c in cases:
        p = SAMPLES / f"{c['id']}.json"
        if p.exists():
            print(f"{c['id']}: {augment(p, cli, device)}", flush=True)
    embedder.free()


if __name__ == "__main__":
    main()
