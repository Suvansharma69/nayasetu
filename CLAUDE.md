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
- **Zero recurring cost.** Never introduce a paid API, paid service, or paid tier without flagging it first.
- **Generation is FULLY LOCAL. There is no cloud path.** *Amended 2026-09-22.* The original plan made Gemini's free tier primary with Ollama as fallback. That was reversed on two grounds: no account or API key should be needed to run this, and no case facts should leave the machine. The second matters most - the corpus here is public judgment data, but the Streamlit form in Phase 7 invites a lawyer to type a real client's facts, and a free-tier cloud provider that may train on prompts is the wrong place for those. Ollama `qwen3.5:4b` is now the ONLY generation path. Do not reintroduce a cloud LLM without flagging it.
  - This is less costly to quality than it sounds, because the LLM does less work here than in a typical RAG app: **Node 2 (the verifier) is deterministic graph lookup, not an LLM**, Node 5 is pure SQL, Node 3 is retrieval. The model only proposes candidate sections in Node 1 - which Node 2 then verifies anyway - and writes counter-arguments in Node 4.
  - The real cost lands on **Node 4**, which is the quality-sensitive one. If its output is weak the fix is better retrieval and better prompting, never fine-tuning (see the RAG-not-fine-tuning rule above).
  - **Consequence: the 4GB VRAM conflict is now central, not a Phase 7 footnote.** The embedder and the Ollama model cannot both hold the card. Every runtime path must free the SentenceTransformer (or pin it to CPU for single-query encoding) before generating.
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
| Generation — the only path | Ollama, `qwen3.5:4b`, local. Degrade to `qwen3.5:2b` (2.7GB) if too slow on the 3050 Ti. **No cloud LLM** - see Section 2 |
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
pip install sentence-transformers chromadb networkx langgraph fastapi uvicorn streamlit python-dotenv pytest pymupdf pandas

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
FastAPI endpoint wrapping the full pipeline. Streamlit form (case facts + offence date) → structured report, verified vs. unconfirmed visually distinct. Generation runs on local Ollama, so **the VRAM handoff is part of this phase's work, not an afterthought**: free the SentenceTransformer (or pin it to CPU) before invoking the model, since both cannot hold the 4GB card.
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

**Current phase:** Phase 1 (Data Layer) IN PROGRESS on `phase-1-data` (2026-09-24). Ingestion is built and the corpus is on disk; the mapping table still needs human sign-off. Phase 2's test set now exists and is committed, so Phase 2 is unblocked apart from that sign-off.

**Session of 2026-09-24/25 (BNS titles).** All 358 BNS sections now carry their correct marginal-note title (was 11 missing + 4 wrong; see Known Gotchas). Corpus rebuilt - the previous rebuild had been killed mid-write, leaving `judgments_post2024.jsonl` at 0 lines while `build_report.json` claimed 42,890; if the two ever disagree again, trust `wc -l`, not the report. Mapping candidates regenerated against the corrected titles: no proposed target changed, only titles/scores. 74 tests pass.

**Session of 2026-09-25 (BNS title reconciliation, `bb31743`).** Closed the "351 notes vs 11 missing titles" question left open above. Both figures were extraction artefacts: **all 358 BNS sections have a marginal note**, and `bns_missing_titles` is now `[]`. Two real bugs, one of which was corrupting data rather than merely omitting it - 11 titles were being glued into neighbouring sections' body text, and 5 sections carried a title that was not theirs (3 from the page-wrap rule, plus s167 holding an act reference and s174 holding two fused titles). See the dated Known Gotchas block for the geometry and the rule that replaced it. `statutes_bns.jsonl` rebuilt: 11 titles gained, 5 corrected, 0 lost, 11 body texts cleaned; judgment corpora byte-identical, `spotcheck.py` still clean with the same 5 Devanagari warnings. 18 new tests in `tests/ingest/test_statutes.py` (74 total). `ipc_bns_candidates.json` regenerated against the corrected titles - **0 proposed targets changed**, 8 similarity scores moved, still 0 of 574 verified, so no human sign-off was lost.
  - Worth knowing before the sign-off: the "Punishment for X" weakness is live in the `in_scope` set. IPC 379 (theft) and 302 (murder) both propose **BNS 46 "Abettor"**, and IPC 406 proposes **BNS 111 "Organised crime"**. All three are wrong and all three carry `low_evidence: true` - the flag is working, but do not skim past a flagged row.

**Session of 2026-09-24 (short session, Phase 2 prep only).** Wrote `tests/fixtures/phase2_testset.json` - the 15 hand-written case-fact examples Section 8 requires, which did not exist and which `embedding_bakeoff.py` needs for the run that decides the embedder. 8 IPC-era cases and 7 BNS-era, covering theft (6), cheating (3), assault (3), common intention (2) and one criminal-breach-of-trust discriminator paired against a theft-by-servant case. Case 9 is the Section 3 motorcycle worked example verbatim.
  - It holds **no statutory text**: `corpus_from` names the two ingested JSONL files, so the corpus is all 932 real sections loaded at run time and the fixture can never drift from what was ingested. Every one of the 33 section ids in it was read out of the real ingested text before being assigned - none from memory. The queries are synthetic facts and say so.
  - It lives in `tests/fixtures/`, **not** `data/processed/`, because that directory is gitignored as rebuildable output and a `.gitignore` negation cannot rescue a file inside an excluded directory. Hand-written source belongs with the smoke fixture.
  - `embedding_bakeoff.py` gained `corpus_from` loading and per-case `era` masking to go with it; `load_data` now refuses a case whose `era` excludes its own answers. 56 tests pass. **The bake-off has NOT been run** - Section 8's gate is "top-3 manually judged relevant", which is a human read, so the deciding run belongs to the Phase 2 session.
  - **Still needs a lawyer's eye:** the `relevant` lists encode "which section do these facts disclose", which is a legal call, not a retrieval one. Case 5 flags s326 as arguable (is an iron rod a dangerous means?). Case 8 depends on there being four accused and not five - do not raise the party count, it would turn s34 into s149.

**Done in the 2026-09-22 session.** `scripts/build_corpus.py` turns raw sources into the four Phase 2 corpora in `data/processed/` as JSONL, validating every record against `src/ingest/schema.py` on the way out:

| corpus | records |
|---|---|
| `statutes_ipc.jsonl` | 574 sections (575 minus s304B, see below) |
| `statutes_bns.jsonl` | 358 sections, all of them, no gaps |
| `judgments_pre2024.jsonl` + `judgments_post2024.jsonl` | ~75K paragraph chunks from 2,533 SC judgments |

`scripts/spotcheck.py` is the Phase 1 gate: it re-validates what is on disk (not just what the build emitted), runs truncation/encoding heuristics over the whole corpus, and prints a seeded random sample to read. 56 unit tests pass (`venv\Scripts\python.exe -m pytest tests/ -q`); `tests/ingest/` covers the schema and the section extractor.

**Still to do before Phase 1 can be called done:** hand-verify the IPC<->BNS mapping. `scripts/build_mapping.py` proposes 574 candidates into `data/mappings/ipc_bns_candidates.json`, every row `"verified": false`. Spot-checked against 21 known correspondences it gets 19 right, and **both misses carry `low_evidence: true`** - so the flag is doing its job, but the rows still need a person. Verify the 97 `in_scope` rows first; they are what the Phase 2 test cases exercise.

**`qwen3.5:4b` is NOT pulled, and that is now BLOCKING for Phase 4.** With the cloud path removed (Section 2), this model is the only way the system generates anything - it is no longer a fallback that can be deferred. `ollama pull qwen3.5:4b`. Still not pulled as of 2026-09-24 - confirmed absent from `ollama list`, with no partial blobs in `D:\ollama\models\blobs`, so no pull is part-done either. Do NOT substitute `qwen3.5:latest`, which is 9.7B and **is already installed at 6.6GB** - it sits right next to the name you want, and it will not fit the 4GB card.

BGE-M3 is **downloaded and verified**: loads on the card at dim=1024, 2.12GB peak VRAM (InLegal-Sbert: dim=768, 0.44GB). Both fit, so the Phase 2 bake-off can run. Note it took **4.3GB on disk, not the ~2.3GB estimated**, and 2.2GB of that is an `onnx/` directory sentence-transformers never loads - prunable.

No API keys are needed anywhere in this project any more.

**Blocked, needs you:** NyayaAnumana is a GATED HuggingFace dataset (401 `GatedRepo` unauthenticated). To ingest it: log in at huggingface.co, open `L-NLProc/NyayaAnumana-Classification-Data`, accept the terms, create a read token, put `HF_TOKEN` in `.env`. Its bulk train splits (6.5GB/4.7GB) are forbidden by Section 4 anyway; the usable piece is `test/2020_2024_single.zip` at 264MB. Without it the corpus is SC-only, which will make Phase 5's >=5-judgments-per-section guardrail suppress most sections.

**Next:** finish the mapping sign-off (human, `scripts\review_mapping.py`, 0 of 574 rows done, `ipc_bns_map.json` not yet created), then Phase 2 (Retrieval). Phase 2 needs the embedder; Phase 1 needed neither embedder nor LLM.

First action of the Phase 2 session, once the mapping is signed off: `venv\Scripts\python.exe scripts\embedding_bakeoff.py --data tests\fixtures\phase2_testset.json`, then **read the per-case top-3 yourself** - the gate is a manual relevance judgement, not the recall number the script prints. Lock the winner into `EMBEDDING_MODEL` before any mass embedding.

`data/raw/` (750MB) is still on disk and must NOT be deleted yet, despite Section 4 rule 4: `src/ingest/statutes.py` reads `data/raw/statutes`, and `review_mapping.py` needs it to show real gazette text. Delete it after the sign-off, not before.

## Known Gotchas

*Resolved 2026-09-20, before Phase 0 - four points where this file disagreed with the actual machine.*

- **Project root is `D:\nayasetu`, not `D:\nayasetu\pramana`.** Section 7's tree labels the project, not a directory to create. Don't "fix" this by nesting a `pramana/` folder.
- ~~**`google-generativeai` is retired; use `google-genai`.**~~ **Obsolete as of 2026-09-22** - there is no cloud generation path at all now (Section 2). Kept only so a future session does not "restore" a Gemini SDK on the strength of an old tutorial. If a cloud LLM is ever reintroduced, it is `google-genai`, never `google-generativeai`.
- **The 20GB ceiling in Section 4 is a deliberate discipline, not a reading of the disk.** `D:` actually has ~107GB free. The ceiling was kept anyway - smaller curated data embeds faster on 4GB VRAM and keeps iteration tight. Seeing free space is *not* grounds to widen dataset scope; Section 4 rule 5 still stands.
- **Ollama models must live on `D:`, never `C:`.** `C:` has only ~10GB free, and 20.67GB of old models were sitting in `C:\Users\<user>\.ollama\models` even though `OLLAMA_MODELS` was set to `D:\stuff` - the *user-level* env var never reached the Ollama background service. Setting `OLLAMA_MODELS` alone is insufficient: the service must be restarted (or the var set machine-wide) for it to take effect. The same trap applies to `pip`'s wheel cache, which defaults to `C:` and holds ~2.5GB for the CUDA torch build - redirect it before installing.
- **InLegal-Sbert is `bhavyagiri/InLegal-Sbert`, NOT `law-ai/InLegalBERT`.** Easy to conflate: InLegal-Sbert is *adapted from* InLegalBERT, but only the Sbert variant has the trained pooling layer that makes it sentence-transformers compatible (768-dim). Loading the base `law-ai/InLegalBERT` through `SentenceTransformer` does **not** error - it silently attaches an untrained mean-pooling head and yields materially worse retrieval. If Phase 2 relevance is bad, check this env var before touching chunking. **There is a full local copy of the WRONG one at `D:\legal\InLegalBERT`** (510MB, the same donor tree the venv's torch came from). It has no `modules.json`, no `1_Pooling/`, no `2_Dense/` - verified. Do not reach for it as a shortcut when the download is failing; it is not a substitute.
- **`gemma3:4b` was dropped for `qwen3.5:4b`.** gemma3:4b is 3.3GB on a 4096 MiB card; after ~0.5-0.8GB of Windows desktop VRAM there is almost nothing left for KV cache, so it spills to CPU. qwen3.5:4b is comparable on disk (3.4GB) but stronger at reasoning and carries a **256K context window**, which matters when stuffing retrieved judgment chunks into a prompt. If it proves too slow on the 3050 Ti, drop to `qwen3.5:2b` (2.7GB), which genuinely fits in VRAM. Do not "restore" gemma3:4b.
- **The embedder and the Ollama fallback cannot both hold VRAM.** 4GB total. At runtime the query is embedded immediately before generation, so Phase 7 must free the SentenceTransformer (or pin it to CPU for single-query encoding) before invoking Ollama. Encoding one query on CPU costs milliseconds; this is not a reason to claw back VRAM elsewhere.
- ~~**Gemini free tier is Flash-only since May 2026.**~~ **Obsolete as of 2026-09-22 - generation is fully local, see Section 2.** The reason is preserved because it is the reason: Google may train on free-tier prompts. That is fine for public judgment data but wrong for the Phase 7 Streamlit form, which invites a lawyer to type a real client's facts. Any future proposal to add a cloud LLM has to answer that.
- **The network link here is slow (~700 KB/s).** The 2.6GB torch wheel and any Ollama pull each take roughly an hour. Do not run two large downloads concurrently, and do not assume a slow-looking download is hung.
- **The venv was seeded by copying torch from `D:\legal\venv`, not by downloading it.** On a ~700 KB/s link the 2.6GB wheel takes an hour; the machine already had five CUDA torch builds on Python 3.12.7. Copied `torch 2.6.0+cu124` plus `transformers`/`tokenizers`/`numpy`/`huggingface_hub`/`safetensors` and friends into `D:\nayasetu\venv\Lib\site-packages`, verified with a real GPU matmul. **This only works because donor and target are byte-identical Python versions** (3.12.7, `_C.cp312-win_amd64.pyd`) - a 3.11 donor would import-error on the compiled extension. `torchaudio`/`torchvision` were deliberately left behind as unused GBs against the Section 4 budget. If `D:\legal\venv` is ever deleted this venv is unaffected; the files were copied, not linked.
- **Installed torch is 2.6.0+cu124, not the newest.** It came from the donor. Fine for everything here (sentence-transformers needs only >=1.11). Do not "upgrade" it casually - that means re-downloading 2.6GB on a slow link for no gain.
- **`HF_HUB_DISABLE_SYMLINKS_WARNING` does not disable symlinks - `HF_HUB_DISABLE_SYMLINKS` does.** Easy to conflate; only one of them is load-bearing. With just the `_WARNING` var set, `huggingface_hub` still *attempts* symlinks into `D:\hf-cache` and dies partway through a model download with `OSError: [WinError 1314] A required privilege is not held by the client` (Windows refuses symlinks without Developer Mode or admin). Both vars are now set in `.env.example` and defaulted in `scripts/check_env.py` and `scripts/embedding_bakeoff.py`. Symptom to recognise: a `SentenceTransformer(...)` load failing with `Can't load the model for '<id>' ... make sure it is the correct path to a directory containing a file named pytorch_model.bin` - that is a **truncated download**, not a wrong model id. Check `D:\hf-cache\hub\models--*/blobs/` for a `.incomplete` file before doubting the id.
- **An interrupted HF download NEVER resumes - by design, not by accident.** `file_download.py` names the temp file `<etag>.<uuid4[:8]>.incomplete`, a fresh random suffix per process (huggingface_hub PR #4228: a shared `<etag>.incomplete` corrupts the cache wherever `flock` silently succeeds for every caller, as on some NFS/Lustre mounts). A killed download therefore leaves orphaned bytes that are never reused, and every retry restarts from 0. Delete stale `.incomplete` blobs by hand; never plan around a retry picking up where it left off.
- **Xet, not plain HTTPS, is the default download path - and it stalled here.** `hf_xet` is installed and `HF_XET_CACHE` is `D:\hf-cache\xet`. Two consequences. (a) On the Xet path the `.incomplete` blob sits at **0 bytes** for the whole transfer, so watching blob size makes a healthy download look hung - measure the whole cache (`du -sk /d/hf-cache`) instead. (b) On this machine Xet genuinely stalled: the cache grew 3.2MB to 3.6MB over several minutes while a plain `curl` of the same `resolve/main/pytorch_model.bin` URL pulled ~480 KB/s. Fix is `HF_HUB_DISABLE_XET=1`, read at import time, so set it before importing `huggingface_hub`.
- **The ~700 KB/s figure above is optimistic, and the link is highly variable.** Measured back-to-back against huggingface.co: 27 KB/s, then 484 KB/s a minute later; github.com 18 KB/s and pypi 168 KB/s in the same window. Budget download time from a fresh measurement, not from the quoted number. Do not conclude a transfer is dead from one slow sample - but do check that bytes are landing at all, which is a different failure (see Xet above).

*Added 2026-09-22 during Phase 1.*

- **The slow-link gotcha does NOT apply to the judgment bucket.** `indian-supreme-court-judgments` is in S3 `ap-south-1` (Mumbai) and pulled all 783.8MB in about a minute. The ~700 KB/s figure is about huggingface.co and github.com specifically. Measure the host you are actually using before budgeting an hour for it.
- **Section 4's vanga estimate was ~7x too high, because it counted the regional tars.** Each year ships `english.tar` AND `regional.tar` (Indian-language translations, ~1-2GB/yr). English only: 2023 = 401MB, 2024 = 203MB, 2025 = 177MB. Pramana is English end to end - InLegal-Sbert is an English model - so regional is pure cost. **Never pull `regional/`.**
- **2025 judgments were added to Section 4's "2023 and 2024 only", deliberately.** BNS binds offences on/after 2024-07-01, and appeals take years, so nothing charged under BNS had reached a Supreme Court judgment by Dec 2024. Without 2025 the `judgments_post2024` collection contains judgments *decided* after the transition that still cite the IPC exclusively - i.e. no BNS precedent at all. The extra 177MB is trivial against a line item budgeted at 4-5GB.
- **NyayaAnumana is GATED.** Unauthenticated fetch returns 401 `GatedRepo`. Needs an HF account, accepted terms and `HF_TOKEN`. Do not plan around it being pullable; the tree/metadata API responds publicly even though the content does not, so a size listing succeeding proves nothing.
- **The judgment archive contains PDFs, not text.** 2,533 of them. They are digital-born with a real text layer (no OCR needed; zero U+FFFD in sampled English text). **pymupdf** is the extractor, chosen by measurement: 0.02s vs pypdf 0.15s vs pdfplumber 0.84s on an 18-page judgment, at slightly *better* completeness. pypdf/pdfplumber were uninstalled after the comparison.
- **There is no trustworthy machine-readable BNS.** Every BNS repo on GitHub is an unvetted 0-2 star hobby project - disqualifying for a system whose premise is that a citation is real only if it came from verified ingested data. Use the MHA gazette PDF (`https://www.mha.gov.in/sites/default/files/250883_english_01042024.pdf`, No. 45 of 2023, digitally signed by Government of India Press). **indiacode.nic.in serves its root but times out on every `/handle/` and `/bitstream/` path from this network** - do not plan on it.
- **The BNS gazette glues words together and it is not the extractor's fault.** "ThisAct maybe called", "intoforce", "(a)Awriting". pymupdf, pypdf and pdfplumber all reproduce it identically - it is the PDF's own kerning. Repair by rule (`_degazette`), never by switching extractor, and never guess at statutory wording.
- **BNS section heads have NO guaranteed space after the period.** 8 of 358 render as `104.Whoever` / `331.(1)`. A regex requiring `\.\s` silently loses exactly those eight. Sections are strictly 1..358 in order, so require each head to be *one past the last accepted* - that is what stops cross-references inside a provision opening a phantom section.
- **BNS section titles are gazette MARGINAL NOTES, and the margin mirrors by page.** Narrow column (width < 80pt), `x0 > 480` on odd pages and `x0 < 110` on even. Match a note to the head nearest it vertically. Two traps: a section starting in the last ~200pt of a page has its note set at the top of the NEXT page (10 sections), and the margin also carries references to other Acts ("28 of 1961.") which are not titles. There are 351 title notes for 358 sections, so **never match the Nth note to the Nth section** - one missing note shifts every title after it, and a shifted title is far worse than an empty one.
- **IPC 304B (dowry death) is EMPTY UPSTREAM.** `section_desc` is `""` in civictech's `ipc.json` and NULL in its `IndiaLaw.db` - the same defect in both formats, not a parsing error. It is the only genuinely-missing IPC section. Tracked in `data/mappings/statute_patches.json`, which is the only sanctioned place to add statutory text, and only transcribed from real gazette text with provenance recorded. **Never write statutory text from memory into this project's corpus.**
- **IPC 13/15/16 are real sections that are 35 characters long** ("Queen. [Repealed by the A. O. 1950]"). A blanket minimum-length filter deletes them. A lawyer citing a repealed section must be told it was repealed, not that it does not exist - so the length floor is doc-type aware (`MIN_STATUTE_TEXT_CHARS = 10` vs 40 for judgments).
- **"120-B" must not be truncated to "120".** Courts write IPC 120B both ways. Stopping the regex at the digits yields s120 (concealing a design) instead of s120B (criminal conspiracy) - a real but unrelated section, so it passes a membership check and lands a wrong edge in the citation graph while looking perfectly verified.
- **Never validate a citation against the UNION of IPC and BNS sections.** The codes renumbered everything: s302 is murder (IPC) vs wounding religious feelings (BNS); s303 is theft (BNS) but was punishment-for-murder-by-a-life-convict (IPC). Detect the corpus first (the SCR "List of Acts" block states it), then validate against that code only. Union is the fallback for genuinely ambiguous transition-era judgments, never the default.
- **Requiring whitespace after a paragraph number is load-bearing.** Judgments are full of `dd.mm.yyyy` dates and line wrapping puts them at line starts ("in letter dated \n25.09.2015"). With the separator optional, "25." opens phantom paragraph 25 and severs the real one mid-sentence. This manufactured 1,741 fake chunks before it was caught - i.e. the parser was creating the exact truncation the Phase 1 gate exists to detect.
- **SCR judgments carry margin position letters A-H as lone lines** (used for pinpoint cites like "at 691-C"). They appear in 7.7% of chunks, often eight in a row at a page break. Strip as page furniture or they get embedded as content.
- **Mojibake in this corpus is Devanagari, and it is a source limitation.** 5 chunks of ~76K contain U+FFFD, every one inside a Hindi/Sanskrit/Urdu passage quoted within an English judgment; the PDFs' Devanagari font mapping is lossy. Surrounding English is intact. Reported as a warning, not a build failure - but if U+FFFD ever shows up in English text, that IS our bug.
- **Similarity scoring for the IPC<->BNS mapping got this wrong twice; use the OVERLAP COEFFICIENT.** Sorting content words into a string and running `SequenceMatcher` compares character runs, not words - it matched IPC 378 (theft) to BNS 97 (selling a child for prostitution). Plain Jaccard scored the *correct* pair (IPC 378 -> BNS 303) at 0.056, because the corpora are shaped differently: IPC records are the bare provision (13 content words) while gazette BNS sections inline all Explanations and Illustrations (233), and the BNS merged provisions the IPC split. `|A&B| / min(|A|,|B|)` separates true pairs (theft 1.00, cheating 0.96, murder 0.86) from false ones (0.31). It still fails on short "Punishment for X" sections that are mostly boilerplate - those are flagged `low_evidence`, and that flag caught both of the 2 misses out of 21.

- **Ligature glyphs are padded with spaces and this silently destroys common legal vocabulary.** The SCR and gazette PDFs use real ligatures, and extraction emits the glyph plus `len(expansion) - 1` spaces because the PDF reserved that width: `ﬁ led` is "filed", `Classiﬁ cation` is "Classification", `Oﬃ  cer` is "Officer" (two spaces - ﬃ expands to three chars). This hit **8.6% of judgment chunks**, and the damaged words are exactly the ones that matter - notification, qualification, definition, specified, effect, benefit. None would ever match a query embedding. Repair by consuming exactly `len(expansion) - 1` spaces, which is also what keeps a word-final `staﬀ  and` from fusing into "staffand". **This must run BEFORE any whitespace collapsing** - collapsing runs of spaces first erases the very signal that distinguishes padding from a real word break.
- **"SUPREME COURT REPORTS" was landing inside 17% of chunks.** The recurring page-break block is, in order: party names in full caps, the authoring judge (`[J. B. PARDIWALA, J.]`), `SUPREME COURT REPORTS`, the reporter citation, the page number. All five are furniture. Match the party-name line **case-sensitively** - it is set in full caps while ordinary prose naming the same parties is not, and that distinction is the only thing stopping the strip from deleting real reasoning. There is a test pinning that (`test_ordinary_prose_naming_parties_is_kept`).
- **BGE-M3 is ~4.3GB downloaded, not the ~2.3GB estimated - and half of it is dead weight.** The real weights are `pytorch_model.bin` at 2.1GB; `snapshot_download` also pulls an `onnx/` directory of 2.2GB that `sentence-transformers` never touches. Fetch with an `ignore_patterns=["onnx/*"]` or prune after. Budget the honest number in Section 4.
- **The Phase 1 gate is a real gate, not a formality.** Reading 20 random chunks surfaced both the ligature damage and the running headers after the corpus had already passed schema validation, zero duplicates and zero encoding errors. Automated checks confirmed the shape was right; only reading the text showed the *content* was wrong. Do not skip the human read.

*Added 2026-09-24 while building the Phase 2 test set.*

- **Statute text keeps the gazette's hard line wraps, so phrase search over it silently fails.** BNS s3(5) contains `common\nintention`, and `text.lower().find("common intention")` therefore returns -1 on a section that plainly contains the provision. **356 of 358 BNS sections carry a newline** (IPC: only 38 of 574, because that corpus came from structured JSON rather than a PDF). Whitespace-normalise before any substring or regex check over statute text - `re.sub(r"\s+", " ", text)`. This does *not* affect embeddings, since tokenizers treat `\n` as whitespace, and it does not affect the mapping scorer, which splits on whitespace already. It will bite anything that keyword-matches: do not conclude a provision is missing from the corpus on the strength of a failed phrase search.
- **A `�` in terminal output is usually the console, not the corpus.** IPC text printed through this shell renders `person's` as `person�s` because the Windows console is cp1252 and the real character is U+2019. Verified by counting U+FFFD in the files directly: **0 in both statute corpora, exactly 5 in `judgments_post2024`** - which matches the known Devanagari cases and nothing else. Check the bytes before believing an encoding bug; and note the earlier gotcha still stands, U+FFFD inside *English* text would be ours.
- **The `OLLAMA_MODELS`-on-`C:` trap is FIXED, and the fix is worth keeping visible.** Models now live in `D:\ollama\models` (21.2GB), the user-level var points there, and the running service confirms it - `Invoke-RestMethod http://127.0.0.1:11434/api/tags` lists them, which is the check that actually proves the *service* agrees rather than the shell. `C:\Users\<user>\.ollama\models` is gone and `C:` free space went from ~10GB to 28.3GB. Keep the lesson (setting the var is not enough, the service must be restarted) but stop treating the old 20.67GB as live.
- **Six unrelated Ollama models are occupying 21.2GB against a line item budgeted at 3.4GB.** `qwen3.5:latest` (6.6GB), `qwen3:8b` (5.2GB), `llama3:latest` (4.7GB), `llama3.1:8b-instruct-q4_0` (4.7GB), `deepseek-coder`, `nomic-embed-text`. None is used by Pramana. **`qwen3.5:latest` is the 9.7B model, not a stand-in for `qwen3.5:4b`** - keeping it next to the real one is an invitation to reach for the wrong name.
- **The venv is 5.5GB, a gigabyte over Section 4's ~4.5GB estimate**, and `D:\hf-cache` adds 5.2GB (2.2GB of it BGE-M3's unused `onnx/`). Not fatal - `D:` has 74.4GB free - but Section 4's figures are now measurably optimistic on two lines at once, so re-measure before trusting the total.
- **Never score retrieval against the union of the IPC and BNS corpora.** The union rule in Known Gotchas is about *validating citations*; it applies just as hard to *measuring retrieval*. The offence-date router means a query only ever meets one code, so a union-corpus benchmark measures a problem the system does not have - and measures it wrongly, because a theft query can bank a top-3 "hit" on s303 while retrieving the IPC's punishment-for-murder-by-a-life-convict. `tests/fixtures/phase2_testset.json` tags every case with an `era` and `embedding_bakeoff.py` masks the pool accordingly; `load_data` refuses a case whose `era` excludes its own answers, since that would look like a retrieval failure rather than the typo it is.
- **The BNS puts common intention in s3(5), inside a 4,765-character section titled "General explanations."** One-section-per-chunk therefore gives that provision an embedding dominated by general-exceptions and definitions material, while its IPC twin (s34) is a 256-character section that is nothing but the rule. Expect the BNS common-intention case to be the weakest in the Phase 2 set. If it fails while s34 passes, **the cause is chunking, not the embedder** - and Section 8's instruction is to fix chunking before carrying it forward, not to swap models.
- **An unreconciled count, worth ten minutes before Phase 2.** Known Gotchas says "351 title notes for 358 sections" (7 short), but `data/processed/build_report.json` lists **11** sections with missing titles: 44, 62, 89, 98, 151, 166, 176, 179, 181, 219, 315. Either 4 notes exist but failed to match vertically, or the 351 figure was loose. A titleless section still embeds fine but reads badly in a Phase 7 report.

*Added 2026-09-24 while reconciling the BNS title counts (separate session; the block above is another session's).*

- **That unreconciled count above is now closed, and the answer was worse than either option offered.** Both figures were artefacts. **Every one of the 358 BNS sections has a marginal note**; the extractor was losing 11 of them and misfiling 4 more. `bns_missing_titles` in `build_report.json` is now `[]`. If it is ever non-empty again, that is a parser regression, not a property of the gazette.
- **The left-margin test was `x1 < 110`, and x1 is the wrong coordinate entirely.** Measured over all 102 pages: left-margin notes sit at `x0` 51.1-59.8, right-margin notes at `x0` 485.4-526.6, body text at `x0` 102.8-232.5. **`x0` separates the columns with ~40pt of clearance on both sides; `x1` does not separate them at all** - note `x1` runs from 75.8 to 116.2, so a threshold of 110 cut straight through the middle of the note column and rejected the 11 widest notes. Those notes did not vanish: they were reclassified as *body*, so each one was **concatenated into a section's text** while the section it belonged to shipped with `section_title: null`. Test the margin by `x0`, never by `x1`.
- **A wrong title is far more damaging than a missing one, and the page-wrap rule produced only wrong ones.** The old rule let a section starting at the foot of a page claim the first note at the top of the next page. It fired 3 times and was wrong 3 times: **s97 took s98's title** ("Selling child for purposes of prostitution" landed on the kidnapping provision), **s175 took s176's**, **s180 took s181's**. Because `_bns_chunk` embeds `f"{title}. {desc}"`, a stolen title is embedded as though it were the section's own - it corrupts retrieval *and* the IPC<->BNS mapping scorer while looking perfectly well-formed. The rule is deleted; see the next point for what replaces it.
- **Assign marginal notes by DOCUMENT ORDER, not by nearest-head-within-a-tolerance.** A section's note is everything standing in the margin between head N and head N+1, keyed on a document-wide ordinate (`page * 842 + y`). Three cases that each needed their own heuristic under the old rule now fall out of the one ordering rule: a note split across three blocks rejoins (s315), two notes fused into one block separate (s174 + s175 share a block), and a note set at the top of the next page lands on the section that actually starts there. Allow a note line to begin ~5pt *above* its own head - measured up to 3pt, e.g. s78 "Stalking" - which is safe because consecutive heads are never closer than ~70pt.
- **Work the margin at LINE granularity, but drop furniture at BLOCK granularity.** pymupdf's block grouping does not respect note boundaries, so lines are the right unit for assignment. But act references and the Press's digital signature share the margin column, and at line granularity they interleave into the title beside them - s167 came out as `'Persons subject 45 of 1950. to certain 46 of 1950. Acts'`. Drop those blocks whole, then emit lines from what survives. Two specifics: the act-reference pattern must accept **several refs in one block** (`"46 of 1950. 62 of 1957."`), and the signature is identifiable by position - it is the only margin block below y=740, the lowest real note being 715.4.
- **The Phase 1 gate caught the shape of this but not the substance, again.** `bns_missing_titles` was sitting in `build_report.json` the whole time, listing all 11 sections by number. The build reported it, validation passed, and it was read as a property of the source document rather than a bug. The 4 *wrong* titles were not reported at all, because nothing checks a title it did manage to assign. Same lesson as the ligature damage: an automated check confirms the shape, only reading the content shows it is wrong.

*(Add to this as you hit real issues during the build.)*
