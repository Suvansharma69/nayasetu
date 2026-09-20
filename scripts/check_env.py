"""Phase 0 environment verification.

Run:  venv\Scripts\python.exe scripts_check_env.py

Checks every load-bearing piece of the stack ACTUALLY works, not just imports.
The InLegal-Sbert check is the important one: a green pip install tells you
nothing about whether the model fits in 4GB VRAM at embedding time.
"""
import os
import sys
import shutil
import sqlite3

os.environ.setdefault("HF_HOME", r"D:\hf-cache")

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


@check("InLegal-Sbert on GPU")
def _():
    import torch
    from sentence_transformers import SentenceTransformer
    model_id = os.environ.get("EMBEDDING_MODEL", "bhavyagiri/InLegal-Sbert")
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
    assert emb.shape[1] == 768, f"expected 768-dim, got {emb.shape[1]}"
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


@check("google-genai")
def _():
    from google import genai  # noqa: F401
    import google.genai as g
    key = os.environ.get("GEMINI_API_KEY")
    status = "key present" if key and key != "your-key-here" else "NO KEY YET (.env)"
    return f"{getattr(g, '__version__', 'n/a')} | {status}"


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


@check("ollama fallback")
def _():
    import urllib.request, json
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    with urllib.request.urlopen(f"{host}/api/tags", timeout=10) as r:
        tags = json.load(r)
    names = [m["name"] for m in tags.get("models", [])]
    want = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
    assert any(n.startswith(want.split(":")[0]) for n in names), (
        f"{want} not pulled; have {names}"
    )
    return f"{host} | {want} present ({len(names)} models)"


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
