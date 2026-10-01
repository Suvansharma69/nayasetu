r"""Second-stage reranking of statute candidates with a cross-encoder.

Why (research, 2026-10-01): the retriever, not the LLM, is the measured
bottleneck. ILSIC (EACL Findings 2026) found RAG for Indian statute
identification limited by a retriever that put the right statute in its top 15
only ~32% of the time; every COLIEE 2025 statute-retrieval team used a multi-
stage pipeline -- cheap candidates first, then a cross-encoder or LLM reranker.
Our own Phase 2 numbers say the same: the right section is usually in the top
10-20 but not the top 3. A bi-encoder embeds facts and statute separately; a
cross-encoder reads them TOGETHER, which is what "does this provision describe
these facts" needs.

Model: BAAI/bge-reranker-v2-m3 (568M), the reranker trained alongside our
BGE-M3 embedder. Local weights in D:\hf-cache\local\bge-reranker-v2-m3
(downloaded with a resumable curl; see CLAUDE.md for why not huggingface_hub).
Runs on CPU by default, for the same reason the query embedder does: Ollama
holds the 4GB card. Loaded on demand and freed after use.
"""
from __future__ import annotations

import gc
import os
import re
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("RERANKER_PATH", r"D:\hf-cache\local\bge-reranker-v2-m3"))
MAX_STATUTE_CHARS = 1500

_model = None


def available(path=DEFAULT_PATH):
    return (Path(path) / "model.safetensors").exists() and (Path(path) / "tokenizer.json").exists()


def get(path=DEFAULT_PATH, device=None):
    global _model
    if _model is None:
        from sentence_transformers import CrossEncoder

        _model = CrossEncoder(str(path), device=device or os.environ.get("RERANKER_DEVICE", "cpu"),
                              max_length=512)
    return _model


def free():
    global _model
    _model = None
    gc.collect()


def rerank(facts, candidates, text_of, batch_size=8):
    """Reorder `candidates` (dicts with "section", optional "matched") by
    cross-encoder relevance of (facts, statute text). Adds "rerank_score".

    `text_of(candidate) -> str` supplies the statute text: the matched sub-
    section's own text where there is one (BNS 3(5) inside BNS 3).
    """
    if not candidates:
        return []
    texts = [re.sub(r"\s+", " ", text_of(c) or "")[:MAX_STATUTE_CHARS] for c in candidates]
    scores = get().predict([(facts, t) for t in texts], batch_size=batch_size, show_progress_bar=False)
    out = [{**c, "rerank_score": float(s)} for c, s in zip(candidates, scores)]
    return sorted(out, key=lambda c: -c["rerank_score"])
