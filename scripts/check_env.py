r"""Phase 0 environment verification.

Run:  venv\Scripts\python.exe scripts\check_env.py

Checks every load-bearing piece of the stack ACTUALLY works, not just imports.
The embedder check is the important one: a green pip install tells you
nothing about whether the model fits in 4GB VRAM at embedding time.
"""
import os
import sys
import shutil
import sqlite3
from pathlib import Path

# .env holds EMBEDDING_MODEL, OLLAMA_* and the cache redirects. Load it
# first so those win; the HF_HOME setdefault below is only a last-resort default
# (it MUST NOT fall back to C:, which has ~10GB free -- CLAUDE.md Known Gotchas).
try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(_env)
    _env_note = f"loaded {_env.name}" if _env.exists() else "no .env (using defaults)"
except ImportError:
    _env_note = "python-dotenv missing"

os.environ.setdefault("HF_HOME", r"D:\hf-cache")
# Not just cosmetic: without this, huggingface_hub attempts symlinks and
# aborts mid-download with WinError 1314 on this machine. The _WARNING var
# does NOT do this -- see CLAUDE.md Known Gotchas.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

OK, FAIL, WARN = "[ OK ]", "[FAIL]", "[WARN]"
results = []


def check(name):
    def deco(fn):
        try:
            detail = fn()
            results.append((OK, name, detail))
        except Exception as e:
            results.append((FAIL, name, f"{type(e).__name__}: {e}"))
    return deco


@check(".env")
def _():
    return _env_note


@check("python")
def _():
    v = sys.version_info
    assert v >= (3, 10), f"need >=3.10, got {v.major}.{v.minor}"
    assert "venv" in sys.executable.lower(), f"not running inside venv: {sys.executable}"
    return f"{v.major}.{v.minor}.{v.micro} (venv)"


@check("torch + CUDA")
def _():
    import torch
    assert torch.cuda.is_available(), "CUDA not available - CPU-only wheel installed?"
    name = torch.cuda.get_device_name(0)
    vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
    return f"{torch.__version__} | {name} | {vram:.1f} GB VRAM"


@check("Embedder on GPU")
def _():
    import torch
    from sentence_transformers import SentenceTransformer
    model_id = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")
    assert "InLegalBERT" not in model_id, (
        "EMBEDDING_MODEL is the base MLM model, not the Sbert variant "
        "- see CLAUDE.md Known Gotchas"
    )
    torch.cuda.reset_peak_memory_stats()
    m = SentenceTransformer(model_id, device="cuda")
    # Realistic legal-text batch, not toy strings.
    batch = [
        "The accused dishonestly took the motorcycle out of the complainant's "
        "possession without consent, with intent to permanently deprive him of it."
    ] * 16
    emb = m.encode(batch, batch_size=16, show_progress_bar=False)
    peak = torch.cuda.max_memory_allocated() / 1024**3
    want = int(os.environ.get("EMBEDDING_DIM", "1024"))
    assert emb.shape[1] == want, f"expected {want}-dim (EMBEDDING_DIM), got {emb.shape[1]}"
    return f"{model_id} | dim={emb.shape[1]} | peak VRAM {peak:.2f} GB"


@check("chromadb")
def _():
    import chromadb
    c = chromadb.EphemeralClient()
    col = c.create_collection("smoke")
    col.add(ids=["a"], documents=["theft of a motorcycle"], embeddings=[[0.1] * 768])
    got = col.query(query_embeddings=[[0.1] * 768], n_results=1)
    assert got["ids"][0] == ["a"]
    return f"{chromadb.__version__} | round-trip ok"


@check("networkx")
def _():
    import networkx as nx
    g = nx.DiGraph()
    g.add_node("BNS-303", kind="section")
    g.add_edge("case-1", "BNS-303")
    assert g.has_node("BNS-303") and not g.has_node("BNS-999")
    return f"{nx.__version__} | node lookup ok"


@check("langgraph")
def _():
    import langgraph
    from langgraph.graph import StateGraph, END
    from typing import TypedDict

    class S(TypedDict):
        retry_count: int

    sg = StateGraph(S)
    sg.add_node("n1", lambda s: {"retry_count": s["retry_count"] + 1})
    sg.set_entry_point("n1")
    sg.add_edge("n1", END)
    out = sg.compile().invoke({"retry_count": 0})
    assert out["retry_count"] == 1
    return f"{getattr(langgraph, '__version__', 'n/a')} | StateGraph ok"


@check("no cloud LLM configured")
def _():
    """Generation is fully local (CLAUDE.md Section 2). Assert it stays that way.

    This check exists to FAIL if a cloud key creeps back into .env. The
    reversal was made so that nothing about a case leaves the machine, and a
    stray GEMINI_API_KEY would silently re-enable a path that is supposed to
    be gone.
    """
    leaked = [k for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                          "GROQ_API_KEY", "OPENROUTER_API_KEY")
              if (os.environ.get(k) or "").strip()
              and not os.environ.get(k, "").startswith("your-key")]
    assert not leaked, f"cloud LLM key(s) set: {leaked} -- generation must stay local"
    return "local-only (no cloud generation path)"


@check("fastapi/streamlit")
def _():
    import fastapi, streamlit
    return f"fastapi {fastapi.__version__} | streamlit {streamlit.__version__}"


@check("sqlite (outcomes store)")
def _():
    con = sqlite3.connect(":memory:")
    con.execute("create table t (s text, conviction int)")
    con.execute("insert into t values ('BNS-303', 1)")
    assert con.execute("select count(*) from t").fetchone()[0] == 1
    return f"sqlite {sqlite3.sqlite_version}"


@check("ollama (SOLE generation path)")
def _():
    # No longer a fallback. Since 2026-09-22 this is the only way the system
    # generates anything, so a failure here is not a degraded mode -- Nodes 1
    # and 4 simply cannot run. Blocking for Phase 4 onward.
    #
    # EXACT tag match. A prefix match on the family name ("qwen3.5") is not
    # good enough: it passes on qwen3.5:latest, which is 9.7B/6.1GB and will
    # not fit the 4GB card at all - the precise failure that got gemma3:4b
    # dropped. Reporting the CONFIGURED name while a different tag is
    # installed is a false green.
    import urllib.request, json
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    with urllib.request.urlopen(f"{host}/api/tags", timeout=10) as r:
        tags = json.load(r)
    models = tags.get("models", [])
    want = os.environ.get("OLLAMA_MODEL", "qwen3.5:4b")
    hit = next((m for m in models if m["name"] == want), None)
    assert hit is not None, (
        f"{want} is NOT pulled (exact tag). Installed: "
        f"{sorted(m['name'] for m in models)}. Run: ollama pull {want}"
    )
    gb = hit["size"] / 1024 ** 3
    params = hit.get("details", {}).get("parameter_size", "?")
    quant = hit.get("details", {}).get("quantization_level", "?")
    # Section 4 budgets 3.4GB for this model; the card is 4GB total.
    assert gb <= 4.0, (
        f"{want} is {gb:.1f} GB ({params}) - cannot fit the 4GB card, will "
        f"spill to CPU. Use qwen3.5:4b, or qwen3.5:2b if that is still slow."
    )
    return f"{host} | {want} {gb:.1f} GB ({params}, {quant})"


@check("disk headroom (Section 4)")
def _():
    free = shutil.disk_usage("D:\\").free / 1024**3
    assert free > 5, f"only {free:.1f} GB free on D:"
    return f"D: {free:.1f} GB free"


width = max(len(n) for _, n, _ in results)
print()
for status, name, detail in results:
    print(f"{status} {name.ljust(width)}  {detail}")
failed = [n for s, n, _ in results if s == FAIL]
print()
if failed:
    print(f"{len(failed)} check(s) FAILED: {', '.join(failed)}")
    sys.exit(1)
print(f"All {len(results)} checks passed - Phase 0 environment verified.")
