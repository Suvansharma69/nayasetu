r"""The one embedding model: loaded once, and freeable before generation.

Two constraints from CLAUDE.md shape this module:

* The model is whatever EMBEDDING_MODEL says, and a ChromaDB collection is only
  meaningful when queried with the model that built it (store.py enforces
  that). Switching models means re-embedding the corpus.
* 4GB of VRAM cannot hold this model and the Ollama generator together. Phase 7
  must call free() -- or encode on CPU -- before generating. Encoding one
  query on CPU costs milliseconds, so single queries can simply use CPU.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Before any huggingface import: see CLAUDE.md Known Gotchas. DISABLE_SYMLINKS
# is the load-bearing one (WinError 1314 otherwise); the _WARNING var only
# mutes the message.
os.environ.setdefault("HF_HOME", r"D:\hf-cache")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:                                  # pragma: no cover
    pass

# Decided at the Phase 2 gate (2026-09-26): BGE-M3 put a relevant section in
# the top 3 for 8/15 test cases against InLegal-Sbert's 3/15, and led in
# every variant tried (stuff/docs/embedding_bakeoff.md). EMBEDDING_MODEL overrides.
DEFAULT_MODEL = "BAAI/bge-m3"

# law-ai/InLegalBERT is the base MLM that InLegal-Sbert was adapted FROM. Loaded
# through SentenceTransformer it does not error -- it silently gets an
# untrained mean-pooling head and retrieves materially worse. Refused by name.
_FORBIDDEN = {"law-ai/inlegalbert"}

_model = None
_loaded = None          # (model_id, device) of the resident model


def model_id():
    mid = os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL).strip()
    if mid.lower() in _FORBIDDEN or mid.replace("\\", "/").lower().endswith("/inlegalbert"):
        raise ValueError(
            f"EMBEDDING_MODEL={mid!r} is the base InLegalBERT, not InLegal-Sbert: it "
            "has no trained pooling layer and silently embeds badly. "
            "Use BAAI/bge-m3 (or bhavyagiri/InLegal-Sbert).")
    return mid


def _device(requested=None):
    import torch

    want = requested or os.environ.get("EMBEDDING_DEVICE", "cuda")
    return want if want == "cpu" or torch.cuda.is_available() else "cpu"


def get(device=None):
    """The resident SentenceTransformer, loading it on first use."""
    global _model, _loaded
    from sentence_transformers import SentenceTransformer

    key = (model_id(), _device(device))
    if _model is None or _loaded != key:
        free()
        kwargs = {}
        if key[1] == "cuda" and os.environ.get("EMBEDDING_FP16", "1") == "1":
            # Half precision on the GPU: roughly twice the throughput and half
            # the VRAM for BGE-M3, with retrieval-level differences in the
            # noise. CPU stays fp32 (fp16 matmuls are slow there). Vectors
            # from both are L2-normalised, so they compare fine.
            import torch

            kwargs["model_kwargs"] = {"torch_dtype": torch.float16}
        _model = SentenceTransformer(key[0], device=key[1], **kwargs)
        _loaded = key
    return _model


def dim():
    return int(get().get_sentence_embedding_dimension())


def encode(texts, batch_size=32, device=None, show_progress_bar=False):
    """L2-normalised embeddings as plain lists (what ChromaDB takes)."""
    if isinstance(texts, str):
        raise TypeError("encode() takes a list of texts; wrap a single query in a list")
    vecs = get(device).encode(
        list(texts), batch_size=batch_size, normalize_embeddings=True,
        convert_to_numpy=True, show_progress_bar=show_progress_bar,
    )
    return vecs.tolist()


def free():
    """Drop the model and return its VRAM -- call before invoking Ollama."""
    global _model, _loaded
    if _model is None:
        return
    _model = None
    _loaded = None
    import gc

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:                              # pragma: no cover
        pass
