# Pramana — Project Context
**Read this file fully before doing anything. This is the single source of truth for the project. If any instruction in a session conflicts with this file, flag the conflict instead of silently picking one.**

---

## 1. What This Is

**Pramana** is an AI-assisted legal research system for Indian criminal law. A lawyer inputs case facts and an offence date; the system identifies applicable statutory provisions (IPC or BNS, whichever era applies), verifies every citation against real ingested data before showing it, matches precedent judgments, generates likely counter-arguments, and produces section-level outcome analytics — conviction rates and sentence ranges pulled from real judgment data.

It is a college capstone project, built to run at **zero recurring cost**, with a **fully local fallback mode**, on a **Windows laptop with roughly 20GB of free disk space** and a 4GB VRAM GPU.

---

## 2. Non-Negotiable Architectural Decisions
**Do not deviate from these without explicitly flagging it and asking first.**

- **RAG, not fine-tuning**, for the generation layer. This is empirically justified: a domain-fine-tuned Indian legal model (AALAP) scored *worse* than an untouched base model on the AIBE benchmark, while a RAG-augmented approach scored highest of everything tested. Never suggest fine-tuning a model as a solution to a quality problem — the fix is better retrieval or better prompting, not fine-tuning.
- **Every citation MUST be checked against the NetworkX citation graph** before being shown as verified. No exceptions. A section number or case ID is only ever "real" if it exists as a node in the graph, built from actually-ingested data.
- **Zero recurring cost.** Never introduce a paid API, paid service, or paid tier without flagging it first. Gemini API free tier is the primary generation path; a local Ollama model is the fallback.
- **Offence-Date Router** (Stage 0, deterministic, no LLM): offence before 1 July 2024 → IPC collections; offence on/after 1 July 2024 → BNS collections + post-2024 judgments. This is load-bearing — every downstream retrieval depends on getting this right.
- **Embedding model: InLegal-Sbert is the DEFAULT, confirmed by measurement at the Phase 2 gate.** `bhavyagiri/InLegal-Sbert` (`sentence-transformers` compatible, adapted from InLegalBERT, domain-pretrained on 5.4M Indian legal documents) - never a generic sentence-transformer picked by default. *Amended 2026-09-20:* domain-pretraining is no longer assumed to settle the question. The Prior Case Retrieval study arXiv 2507.18455 evaluated PCR on Indian legal data and found general-purpose embedders match or beat InLegalBERT/InLegal-Sbert. So the choice is decided by `scripts/embedding_bakeoff.py` against the 15 Phase 2 test cases, not by assertion. **The winner is locked before mass ingestion** - changing embedder afterwards means re-embedding the whole corpus. Candidates are capped by the 4GB VRAM / 20GB disk budget, which rules out all 7B-class leaderboard leaders.
- **GPU-accelerated PyTorch (CUDA build)** for embeddings — InLegal-Sbert runs on GPU. This costs more disk space than the CPU-only build (~2GB more), which is accounted for in the Section 4 storage budget. Ollama's fallback model manages its own GPU access independently either way.
- **"Insufficient data" guardrail**: if retrieval returns nothing relevant above threshold, return an explicit "insufficient data" response rather than forcing the LLM to generate an answer from weak context.

---

## 3. System Architecture

```
OFFLINE (built once):
Data ingestion → preprocessing → legal embeddings (InLegal-Sbert) → ChromaDB
                                                                    ↘
                                                          Citation Graph (NetworkX)

RUNTIME (per case):
Input (case facts + offence date)
  → Stage 0: Offence-Date Router (deterministic)
  → Retrieval (InLegal-Sbert encodes query, searches ChromaDB)
  → [insufficient data? → return early, skip LLM]
  → LangGraph pipeline:
       Node 1: Statute Identifier   (proposes candidate_sections)
       Node 2: Verifier              (checks against citation graph → verified_sections)
                 ↳ conditional edge: if unconfirmed and retry_count < 2 → back to Node 1, with feedback
       Node 3: Precedent Matcher     (retrieves judgments for verified sections;
                                       for post-2024 cases, ALSO checks the IPC-predecessor
                                       section via the mapping table — precedent shouldn't
                                       be cut off artificially at the BNS transition date)
       Node 4: Defense Generator     (counter-arguments from verified_sections + precedents)
       Node 5: Outcome Analytics     (runs in PARALLEL with Node 3 — reads only
                                       verified_sections, pure SQL aggregation over a
                                       pre-extracted outcomes table, NO LLM call at runtime,
                                       suppressed below ~5 supporting judgments)
  → Final verification pass (re-check any new citations Node 3/4 introduced)
  → FastAPI backend → Streamlit report (verified vs. unconfirmed MUST be visually distinct)
```

**LangGraph shared state schema** (exact field names to use):
```python
state = {
    "case_facts": str,
    "offence_date": str,
    "candidate_sections": list,
    "verified_sections": list,
    "precedents": list,
    "analytics": dict,
    "defenses": list,
    "retry_count": int,
}
```

**Worked example to test against** (use this as your standard end-to-end test case): a case description mentioning theft of a motorcycle, offence date 15 August 2024. Router selects BNS (date is after 1 Jul 2024). Retrieval surfaces BNS §303 (theft). Node 1 proposes §303. Node 2 confirms it's a real ingested section. Node 3 retrieves judgments applying §303 *and* checks its IPC predecessor, §378, for pre-transition precedent where legally relevant. Node 4 proposes counter-arguments grounded only in verified sections and matched precedents.

---

## 4. Dataset & Storage Plan — Hard 20GB Ceiling

This is a genuine constraint, not a preference. Budget:

| Item | Budget |
|---|---|
| IPC + BNS statute JSON | ~50 MB |
| Python environment (**GPU/CUDA** torch + sentence-transformers + ChromaDB + LangGraph + FastAPI/Streamlit) | ~4.5 GB |
| Ollama + `qwen3.5:4b` (Q4) | ~3.4 GB |
| vanga SC judgments — **2023 and 2024 only**, not the full archive | ~4–5 GB |
| NyayaAnumana — **curated subset of a few thousand cases** filtered to theft/assault/cheating/common-intention offence types, NOT the full 702,945-case collection | ~1–2 GB |
| ChromaDB vector index + citation graph | ~0.5–1 GB |
| Working buffer (git, temp files) | ~3 GB |
| **Total** | **~18.5 GB, leaving only ~1.5 GB headroom** |

**This is noticeably tighter than the CPU-only plan (~1.5GB headroom vs. ~3.5GB) — treat that headroom as real, not padding.** If any dataset estimate below runs high in practice, the fix is trimming a dataset (e.g. 1 year of vanga instead of 2), not assuming there's slack to absorb it.

**Rules to enforce:**
1. Pull vanga's SC judgment archive filtered to **2023 + 2024 specifically** (it's organized by year on S3) — this straddles the IPC→BNS transition, giving real data on both sides of the router logic.
2. Do **not** download NyayaAnumana's bulk collection. Pull a curated, filtered subset.
3. **Download the NyayaAnumana subset first**, check actual remaining disk space, *then* size the vanga pull based on what's really left — don't trust the estimates above blindly, they're estimates, not confirmed figures. With only ~1.5GB headroom under the GPU-enabled plan, check remaining space after every major download, not just at the end.
4. Once `data/processed/` exists and is verified correct, **delete `data/raw/`**. Don't keep both simultaneously — that's paying for the same data twice.
5. If disk space gets tight mid-project, the fix is a smaller data subset, never a bigger disk budget assumption.

---

## 5. Tech Stack

| Layer | Tool |
|---|---|
| Embedding model | InLegal-Sbert default, `bhavyagiri/InLegal-Sbert` - challenger BGE-M3, decided at Phase 2 gate |
| Vector store | ChromaDB (embedded, file-based, 4 collections: `ipc_sections`, `bns_sections`, `judgments_pre2024`, `judgments_post2024`) |
| Citation graph | NetworkX (in-memory, no server) |
| Orchestration | LangGraph |
| Generation — primary | Gemini API free tier - `gemini-3.8-flash`, degrading to `gemini-3.1-flash-lite` on rate limit |
| Generation — fallback | Ollama, `qwen3.5:4b`, local (replaced `gemma3:4b` - see Known Gotchas) |
| Backend | FastAPI |
| Frontend | Streamlit |
| Outcomes storage | SQLite |

---

## 6. Windows-Specific Setup Notes

```powershell
# Virtual environment
python -m venv venv
venv\Scripts\activate

# GPU-accelerated PyTorch (CUDA build). On THIS machine torch was NOT downloaded
# - it was copied from an existing venv (see Known Gotchas). To rebuild from
# scratch, check pytorch.org's "Get Started" selector for the command matching
# your CUDA driver; the installed build is 2.6.0+cu124:
pip install torch --index-url https://download.pytorch.org/whl/cu124

# Rest of requirements
pip install sentence-transformers chromadb networkx langgraph google-genai fastapi uvicorn streamlit python-dotenv pytest

# Ollama (native Windows installer, or winget)
winget install Ollama.Ollama
ollama pull qwen3.5:4b
ollama run qwen3.5:4b "hello"   # confirm it works before you need it as a fallback
```

Claude Code on Windows uses Git Bash for its Bash tool if Git for Windows is installed; otherwise it falls back to PowerShell. Either works for this project — no bash-specific scripting is required by the plan below.

---

## 7. Folder Structure

**Real root on this machine is `D:\nayasetu`** — `pramana/` below names the project, not a nested folder. `data/`, `src/`, `app/`, `tests/` sit directly in `D:\nayasetu`.

```
pramana/                     # == D:\nayasetu
├── data/
│   ├── raw/                 # untouched downloads — delete after processing, never commit
│   ├── processed/           # cleaned, chunked JSON
│   └── mappings/             # IPC↔BNS section mapping table
├── src/
│   ├── ingest/               # Phase 1
│   ├── retrieval/             # Phase 2
│   ├── graph/                 # Phase 3
│   ├── pipeline/               # Phase 4–5 (LangGraph nodes)
│   ├── eval/                   # Phase 6
│   └── api/                    # Phase 7 (FastAPI)
├── app/                     # Streamlit frontend (Phase 7)
├── tests/                   # mirrors src/
├── .env.example              # never commit the real .env
├── requirements.txt
└── CLAUDE.md                # this file
```

---

## 8. The 7 Phases

**Work one phase per session. Start each with `/clear`. Use Plan Mode before writing code on Phase 4 and later — ask for a plan, review it, then approve implementation.**

### Phase 1 — Data Layer (2 weeks)
Pull civictech-India IPC/CrPC JSON, curate BNS dataset, build the IPC↔BNS mapping table (highest-risk task — spot-check against real gazette text, don't fully automate), pull the NyayaAnumana subset and the 2023+2024 vanga judgments per Section 4's storage plan. Chunk statutes one-section-per-chunk; chunk judgments by paragraph/holding, never fixed token count. Every chunk gets metadata: source, court, date, sections_involved.
**Done when:** processed JSON validates against a fixed schema; 20 random chunks manually spot-checked, none truncated or malformed.

### Phase 2 — Retrieval (1 week)
Embed everything with InLegal-Sbert into the four ChromaDB collections. Write one reusable `retrieve(query_text, collection) -> top_k` function. Test against 15 hand-written case-fact examples spanning theft, assault, cheating, common intention.
**Done when:** top-3 results manually judged relevant in at least 12/15 test cases. If not, fix chunking before moving on — don't carry bad retrieval forward.

### Phase 3 — Citation Graph (1 week)
Build the NetworkX graph (section + case nodes, case→section edges from Phase 1 metadata). Implement `verify_section()`, `verify_case()`, `get_precedents_for_section()`.
**Done when:** 100% correct on an adversarial test set of 10 real + 10 fabricated section numbers. This is a binary gate.

### Phase 4 — Single-Node Pipeline (2 weeks)
LangGraph `StateGraph` with the exact schema from Section 3. Implement the Offence-Date Router as a plain function (not a graph node — deterministic, before the graph). Implement the insufficient-data guardrail. Node 1 + Node 2 + the conditional retry edge (cap `retry_count < 2`, feed the specific unconfirmed section back into the retry prompt).
**Done when:** 10 test cases (5 pre-2024, 5 post-2024) route correctly every time; a deliberately-adversarial case demonstrably triggers and survives the retry loop.

### Phase 5 — Full Pipeline (2 weeks)
Node 3 (with the IPC-predecessor check for post-2024 cases), Node 4, and Node 5 (offline outcome-extraction batch job into SQLite, then the runtime SQL-only aggregation with the small-sample guardrail). Wire Node 5 to run in parallel with Node 3.
**Done when:** the motorcycle-theft worked example (Section 3) runs end-to-end and produces a correctly-structured report.

### Phase 6 — Evaluation (1 week)
Evaluate Node 1 and Node 3 against IL-TUR's LSI and PCR tasks. Compute the hallucination-catch-rate: of all citations Node 1 ever proposed, what fraction were caught unconfirmed by Node 2, and what fraction were corrected within 2 retries.
**Done when:** real numbers exist in `docs/evaluation_results.md`, reproducible by re-running one script.

### Phase 7 — Frontend (1 week)
FastAPI endpoint wrapping the full pipeline. Streamlit form (case facts + offence date) → structured report, verified vs. unconfirmed visually distinct. Ollama fallback wired for when Gemini is unavailable.
**Done when:** the motorcycle-theft example works end-to-end in the browser with no manual steps.

---

## 9. Working Discipline

- One phase ≈ one session. `/clear` between phases; `/compact` mid-phase if running long but not done.
- Git: `main` always working; one branch per phase (`phase-1-data`, `phase-2-retrieval`, …); merge only when that phase's "Done when" criteria are actually met — not just when the code runs without errors.
- **Whenever a mistake gets corrected, add it to this file's "Known Gotchas" section below** — don't let the same mistake recur in a later session.
- If a change to citation verification or the retry loop is proposed as a "simplification," treat it with extra scrutiny — this logic is easy to subtly weaken while cleaning it up.

---

## 10. Current Status
*(Update this line at the end of every session.)*

**Current phase:** Phase 0 nearly done (2026-09-21). `scripts/check_env.py` passes **10 of 11** checks: torch 2.6.0+cu124 on the RTX 3050 Ti (4.0GB), chromadb 1.5.9, networkx 3.3, langgraph 1.2.11, google-genai 2.24.0, fastapi 0.141.1 / streamlit 1.64.0, sqlite 3.45.3, Ollama serving `qwen3.5:4b`, 80GB free on `D:`.

**The one open item is the InLegal-Sbert weights.** The 418MB `pytorch_model.bin` is not downloaded - the link died repeatedly (best run reached 23.5MB before `getaddrinfo failed`). Everything else about the model is verified: the repo is correct and its `modules.json` carries the Transformer+Pooling+Dense stack. Re-run `venv\Scripts\python.exe scripts\fetch_models.py` when the network is usable, then `scripts\check_env.py` for a clean 12/12. **This does not block Phase 1** - the data layer needs no embedder. It blocks Phase 2.

Also outstanding: `.env` exists but `GEMINI_API_KEY` is still the placeholder.

## Known Gotchas

*Resolved 2026-09-20, before Phase 0 - four points where this file disagreed with the actual machine.*

- **Project root is `D:\nayasetu`, not `D:\nayasetu\pramana`.** Section 7's tree labels the project, not a directory to create. Don't "fix" this by nesting a `pramana/` folder.
- **`google-generativeai` is retired; use `google-genai`.** Google replaced the SDK. Same free tier, different import surface (`from google import genai`). Section 6 has been updated - don't revert to the old package name just because older tutorials use it.
- **The 20GB ceiling in Section 4 is a deliberate discipline, not a reading of the disk.** `D:` actually has ~107GB free. The ceiling was kept anyway - smaller curated data embeds faster on 4GB VRAM and keeps iteration tight. Seeing free space is *not* grounds to widen dataset scope; Section 4 rule 5 still stands.
- **Ollama models must live on `D:`, never `C:`.** `C:` has only ~10GB free, and 20.67GB of old models were sitting in `C:\Users\<user>\.ollama\models` even though `OLLAMA_MODELS` was set to `D:\stuff` - the *user-level* env var never reached the Ollama background service. Setting `OLLAMA_MODELS` alone is insufficient: the service must be restarted (or the var set machine-wide) for it to take effect. The same trap applies to `pip`'s wheel cache, which defaults to `C:` and holds ~2.5GB for the CUDA torch build - redirect it before installing.
- **InLegal-Sbert is `bhavyagiri/InLegal-Sbert`, NOT `law-ai/InLegalBERT`.** Easy to conflate: InLegal-Sbert is *adapted from* InLegalBERT, but only the Sbert variant has the trained pooling layer that makes it sentence-transformers compatible (768-dim). Loading the base `law-ai/InLegalBERT` through `SentenceTransformer` does **not** error - it silently attaches an untrained mean-pooling head and yields materially worse retrieval. If Phase 2 relevance is bad, check this env var before touching chunking. **There is a full local copy of the WRONG one at `D:\legal\InLegalBERT`** (510MB, the same donor tree the venv's torch came from). It has no `modules.json`, no `1_Pooling/`, no `2_Dense/` - verified. Do not reach for it as a shortcut when the download is failing; it is not a substitute.
- **`gemma3:4b` was dropped for `qwen3.5:4b`.** gemma3:4b is 3.3GB on a 4096 MiB card; after ~0.5-0.8GB of Windows desktop VRAM there is almost nothing left for KV cache, so it spills to CPU. qwen3.5:4b is comparable on disk (3.4GB) but stronger at reasoning and carries a **256K context window**, which matters when stuffing retrieved judgment chunks into a prompt. If it proves too slow on the 3050 Ti, drop to `qwen3.5:2b` (2.7GB), which genuinely fits in VRAM. Do not "restore" gemma3:4b.
- **The embedder and the Ollama fallback cannot both hold VRAM.** 4GB total. At runtime the query is embedded immediately before generation, so Phase 7 must free the SentenceTransformer (or pin it to CPU for single-query encoding) before invoking Ollama. Encoding one query on CPU costs milliseconds; this is not a reason to claw back VRAM elsewhere.
- **Gemini free tier is Flash-only since May 2026.** Pro models moved behind billing. `gemini-3.8-flash` is the newest free Flash; `gemini-3.1-flash-lite` has higher limits and is the degrade target. Do not write `gemini-2.0-flash` or any `*-pro` ID into config. Note also that Google may train on free-tier prompts - fine for public judgment data, but never send a real client's facts through it.
- **The network link here is slow (~700 KB/s).** The 2.6GB torch wheel and any Ollama pull each take roughly an hour. Do not run two large downloads concurrently, and do not assume a slow-looking download is hung.
- **The venv was seeded by copying torch from `D:\legal\venv`, not by downloading it.** On a ~700 KB/s link the 2.6GB wheel takes an hour; the machine already had five CUDA torch builds on Python 3.12.7. Copied `torch 2.6.0+cu124` plus `transformers`/`tokenizers`/`numpy`/`huggingface_hub`/`safetensors` and friends into `D:\nayasetu\venv\Lib\site-packages`, verified with a real GPU matmul. **This only works because donor and target are byte-identical Python versions** (3.12.7, `_C.cp312-win_amd64.pyd`) - a 3.11 donor would import-error on the compiled extension. `torchaudio`/`torchvision` were deliberately left behind as unused GBs against the Section 4 budget. If `D:\legal\venv` is ever deleted this venv is unaffected; the files were copied, not linked.
- **Installed torch is 2.6.0+cu124, not the newest.** It came from the donor. Fine for everything here (sentence-transformers needs only >=1.11). Do not "upgrade" it casually - that means re-downloading 2.6GB on a slow link for no gain.
- **`HF_HUB_DISABLE_SYMLINKS_WARNING` does not disable symlinks - `HF_HUB_DISABLE_SYMLINKS` does.** Easy to conflate; only one of them is load-bearing. With just the `_WARNING` var set, `huggingface_hub` still *attempts* symlinks into `D:\hf-cache` and dies partway through a model download with `OSError: [WinError 1314] A required privilege is not held by the client` (Windows refuses symlinks without Developer Mode or admin). Both vars are now set in `.env.example` and defaulted in `scripts/check_env.py` and `scripts/embedding_bakeoff.py`. Symptom to recognise: a `SentenceTransformer(...)` load failing with `Can't load the model for '<id>' ... make sure it is the correct path to a directory containing a file named pytorch_model.bin` - that is a **truncated download**, not a wrong model id. Check `D:\hf-cache\hub\models--*/blobs/` for a `.incomplete` file before doubting the id.
- **An interrupted HF download NEVER resumes - by design, not by accident.** `file_download.py` names the temp file `<etag>.<uuid4[:8]>.incomplete`, a fresh random suffix per process (huggingface_hub PR #4228: a shared `<etag>.incomplete` corrupts the cache wherever `flock` silently succeeds for every caller, as on some NFS/Lustre mounts). A killed download therefore leaves orphaned bytes that are never reused, and every retry restarts from 0. Delete stale `.incomplete` blobs by hand; never plan around a retry picking up where it left off.
- **Xet, not plain HTTPS, is the default download path - and it stalled here.** `hf_xet` is installed and `HF_XET_CACHE` is `D:\hf-cache\xet`. Two consequences. (a) On the Xet path the `.incomplete` blob sits at **0 bytes** for the whole transfer, so watching blob size makes a healthy download look hung - measure the whole cache (`du -sk /d/hf-cache`) instead. (b) On this machine Xet genuinely stalled: the cache grew 3.2MB to 3.6MB over several minutes while a plain `curl` of the same `resolve/main/pytorch_model.bin` URL pulled ~480 KB/s. Fix is `HF_HUB_DISABLE_XET=1`, read at import time, so set it before importing `huggingface_hub`.
- **The ~700 KB/s figure above is optimistic, and the link is highly variable.** Measured back-to-back against huggingface.co: 27 KB/s, then 484 KB/s a minute later; github.com 18 KB/s and pypi 168 KB/s in the same window. Budget download time from a fresh measurement, not from the quoted number. Do not conclude a transfer is dead from one slow sample - but do check that bytes are landing at all, which is a different failure (see Xet above).

*(Add to this as you hit real issues during the build.)*
