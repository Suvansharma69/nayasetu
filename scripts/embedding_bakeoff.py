"""Embedding model bake-off -- decides CLAUDE.md Section 2's embedder empirically.

Why this exists
---------------
Section 2 originally asserted InLegal-Sbert on domain-pretraining grounds. The
Prior Case Retrieval study (arXiv 2507.18455), run on Indian legal data, found
general-purpose embedders match or beat InLegalBERT/InLegal-Sbert. Rather than
swap on a leaderboard ranking or keep the assertion, we measure on OUR data.

Run it twice:
  1. NOW, on the smoke fixture, just to prove the harness works:
       venv\\Scripts\\python.exe scripts/embedding_bakeoff.py --smoke
  2. AT THE PHASE 2 GATE, on the real 15 hand-written case-fact examples:
       venv\\Scripts\\python.exe scripts/embedding_bakeoff.py --data tests/fixtures/phase2_testset.json

The Phase 2 run is the one that counts. Lock the winner into EMBEDDING_MODEL
BEFORE mass ingestion -- switching later means re-embedding the whole corpus.

Candidates are constrained by 4GB VRAM and the 20GB disk ceiling, which rules
out every 7B-class leaderboard leader (Qwen3-Embedding-8B, SFR-Embedding-2, ...).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("HF_HOME", r"D:\hf-cache")
# Not just cosmetic: without this, huggingface_hub attempts symlinks and
# aborts mid-download with WinError 1314 on this machine. The _WARNING var
# does NOT do this -- see CLAUDE.md Known Gotchas.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

DEFAULT_MODELS = [
    "bhavyagiri/InLegal-Sbert",   # incumbent: domain-pretrained, 110M, 768d, 512 tok
    "BAAI/bge-m3",                # challenger: 568M, 1024d, 8192 tok context
]


def load_data(path):
    """Read a bake-off file. Two corpus forms, and optional per-case eras.

    `corpus`      -- an inline list of {id, text}. The smoke fixture uses this.
    `corpus_from` -- a list of processed JSONL paths, read straight from
                     data/processed/. The Phase 2 set uses this so the test
                     file cannot drift from what was actually ingested, and so
                     no statutory text has to be transcribed into it.

    A case may carry `era` ("ipc" | "bns"). That is not decoration: Stage 0's
    offence-date router means a query is only ever searched against one code's
    collections, so scoring against the union of both would measure a problem
    the system does not have. Worse, it would measure it wrongly -- s303 is
    theft in the BNS but punishment-for-murder-by-a-life-convict in the IPC, so
    a union corpus lets a model bank a hit on the right number from the wrong
    statute. `era` restricts the candidate pool to the code the router would
    have selected.
    """
    blob = json.loads(path.read_text(encoding="utf-8"))
    cases = blob["cases"]

    if "corpus" in blob:
        corpus = blob["corpus"]
    elif "corpus_from" in blob:
        corpus = []
        for rel in blob["corpus_from"]:
            src = ROOT / rel
            if not src.exists():
                raise FileNotFoundError("corpus_from: %s" % src)
            with src.open(encoding="utf-8") as fh:
                for line in fh:
                    rec = json.loads(line)
                    corpus.append({
                        "id": rec["chunk_id"],
                        "text": rec["text"],
                        # `corpus` in the ingested record is "ipc"/"bns" -- the
                        # same vocabulary a case's `era` uses.
                        "era": rec.get("corpus"),
                        "section": rec.get("section"),
                        "section_title": rec.get("section_title"),
                    })
    else:
        raise ValueError("%s has neither 'corpus' nor 'corpus_from'" % path.name)

    ids = {c["id"] for c in corpus}
    for case in cases:
        missing = set(case["relevant"]) - ids
        if missing:
            raise ValueError("case references unknown corpus ids: %s" % missing)

    # An era that excludes a case's own answers would make that case
    # unhittable and silently drag every model's recall down together, which
    # looks like a retrieval problem rather than the typo it is.
    by_id = {c["id"]: c for c in corpus}
    for case in cases:
        era = case.get("era")
        if not era:
            continue
        stranded = [r for r in case["relevant"] if by_id[r].get("era") != era]
        if stranded:
            raise ValueError(
                "case era %r excludes its own relevant ids %s -- the case could "
                "never be scored a hit" % (era, stranded))

    return corpus, cases


def evaluate(model_id, corpus, cases, device):
    import torch
    from sentence_transformers import SentenceTransformer

    if device == "cuda" and torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    else:
        device = "cpu"

    t0 = time.perf_counter()
    model = SentenceTransformer(model_id, device=device)
    load_s = time.perf_counter() - t0

    texts = [c["text"] for c in corpus]
    ids = [c["id"] for c in corpus]

    t0 = time.perf_counter()
    doc_emb = model.encode(
        texts, batch_size=8, normalize_embeddings=True,
        convert_to_tensor=True, show_progress_bar=False,
    )
    encode_s = time.perf_counter() - t0

    q_emb = model.encode(
        [c["query"] for c in cases], batch_size=8, normalize_embeddings=True,
        convert_to_tensor=True, show_progress_bar=False,
    )

    sims = q_emb @ doc_emb.T                      # cosine, both normalized

    # Apply the offence-date router. A case with an `era` competes only against
    # its own code's sections; everything else is pushed below every real
    # candidate rather than dropped, so row widths stay uniform.
    doc_eras = [c.get("era") for c in corpus]
    for row, case in enumerate(cases):
        era = case.get("era")
        if not era:
            continue
        excluded = [i for i, e in enumerate(doc_eras) if e != era]
        if excluded:
            sims[row, excluded] = float("-inf")

    order = sims.argsort(dim=1, descending=True).cpu().tolist()

    hits = {1: 0, 3: 0, 5: 0}
    rr_total = 0.0
    per_case = []
    for case, ranked in zip(cases, order):
        ranked_ids = [ids[i] for i in ranked]
        rel = set(case["relevant"])
        for k in hits:
            if rel & set(ranked_ids[:k]):
                hits[k] += 1
        rank = next((i + 1 for i, d in enumerate(ranked_ids) if d in rel), None)
        rr_total += 1.0 / rank if rank else 0.0
        per_case.append({
            "query": case["query"][:60] + "...",
            "era": case.get("era"),
            "offence_type": case.get("offence_type"),
            "pool": sum(1 for e in doc_eras if not case.get("era") or e == case["era"]),
            "top3": ranked_ids[:3],
            "relevant": sorted(rel),
            "first_hit_rank": rank,
        })

    n = len(cases)
    peak_vram = 0.0
    if device == "cuda" and torch.cuda.is_available():
        peak_vram = torch.cuda.max_memory_allocated() / 1024 ** 3
    dim = int(doc_emb.shape[1])
    max_seq = getattr(model, "max_seq_length", None)

    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return {
        "model": model_id,
        "dim": dim,
        "max_seq_length": max_seq,
        "device": device,
        "load_s": round(load_s, 1),
        "encode_s": round(encode_s, 2),
        "docs_per_s": round(len(texts) / encode_s, 1) if encode_s else 0.0,
        "peak_vram_gb": round(peak_vram, 2),
        "recall@1": round(hits[1] / n, 3),
        "recall@3": round(hits[3] / n, 3),
        "recall@5": round(hits[5] / n, 3),
        "mrr": round(rr_total / n, 3),
        "n_cases": n,
        "per_case": per_case,
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, help="JSON with 'corpus' and 'cases'")
    ap.add_argument("--smoke", action="store_true",
                    help="use tests/fixtures/bakeoff_smoke.json (harness check only)")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--device", default=os.environ.get("EMBEDDING_DEVICE", "cuda"))
    ap.add_argument("--report", type=Path,
                    default=ROOT / "docs" / "embedding_bakeoff.md")
    args = ap.parse_args()

    if args.smoke:
        data_path = ROOT / "tests" / "fixtures" / "bakeoff_smoke.json"
    elif args.data:
        data_path = args.data
    else:
        ap.error("pass --data <file> or --smoke")

    corpus, cases = load_data(data_path)
    smoke = args.smoke or "smoke" in data_path.name
    if smoke:
        print("")
        print("*** SMOKE MODE: fixture data, toy cases. This proves the harness runs.")
        print("*** It does NOT decide the embedder. Re-run at the Phase 2 gate with")
        print("*** the real 15 case-fact examples before locking anything in.")
        print("")

    print("data    : %s  (%d docs, %d cases)" % (data_path, len(corpus), len(cases)))
    print("device  : %s" % args.device)
    print("")

    results = []
    for model_id in args.models:
        print("[running] %s ..." % model_id, flush=True)
        try:
            results.append(evaluate(model_id, corpus, cases, args.device))
        except Exception as e:
            print("[FAILED]  %s: %s: %s" % (model_id, type(e).__name__, e))
            results.append({"model": model_id,
                            "error": "%s: %s" % (type(e).__name__, e)})

    ok = [r for r in results if "error" not in r]
    if not ok:
        print("every candidate failed")
        return 1

    hdr = ("%-30s %5s %6s %6s %6s %6s %6s %7s %8s"
           % ("model", "dim", "ctx", "R@1", "R@3", "R@5", "MRR", "VRAM", "docs/s"))
    print("")
    print(hdr)
    print("-" * len(hdr))
    for r in ok:
        print("%-30s %5d %6s %6s %6s %6s %6s %6sG %8s"
              % (r["model"], r["dim"], r["max_seq_length"], r["recall@1"],
                 r["recall@3"], r["recall@5"], r["mrr"], r["peak_vram_gb"],
                 r["docs_per_s"]))

    # Phase 2's gate is recall@3; MRR breaks ties.
    winner = max(ok, key=lambda r: (r["recall@3"], r["mrr"]))
    print("")
    print("winner on recall@3: %s  (R@3=%s, MRR=%s)"
          % (winner["model"], winner["recall@3"], winner["mrr"]))
    gate = round(12 / 15, 3)
    if not smoke:
        status = "PASSES" if winner["recall@3"] >= gate else "FAILS"
        print("Phase 2 gate (>= %s top-3 relevance): %s" % (gate, status))
        if winner["recall@3"] < gate:
            print("Per CLAUDE.md Section 8: fix chunking before moving on. "
                  "Do NOT carry bad retrieval forward.")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Embedding bake-off",
        "",
        "- data: `%s` (%d docs, %d cases)" % (data_path.name, len(corpus), len(cases)),
        "- device: %s" % args.device,
        "- mode: %s" % ("SMOKE (harness check, not decisive)" if smoke else "PHASE 2 GATE"),
        "",
        "| model | dim | ctx | R@1 | R@3 | R@5 | MRR | peak VRAM | docs/s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in ok:
        lines.append("| `%s` | %d | %s | %s | %s | %s | %s | %s GB | %s |"
                     % (r["model"], r["dim"], r["max_seq_length"], r["recall@1"],
                        r["recall@3"], r["recall@5"], r["mrr"], r["peak_vram_gb"],
                        r["docs_per_s"]))
    for r in results:
        if "error" in r:
            lines.append("| `%s` | - | - | - | - | - | - | - | FAILED: %s |"
                         % (r["model"], r["error"]))
    lines += ["", "**Winner on recall@3:** `%s`" % winner["model"], "",
              "```json", json.dumps(results, indent=2), "```"]
    args.report.write_text("\n".join(lines), encoding="utf-8")
    print("")
    print("report -> %s" % args.report.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
