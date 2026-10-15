# Pramana — The Complete Project Guide

*Written 2026-10-15 from the project's own records (git history, `CLAUDE.md`, the `docs/` evaluation files, the code). Every number here can be traced to one of those files; where a number lives is given in brackets so you can show it if asked. Read Part A once end to end, then use Part F (the question bank) to rehearse.*

**How to use this guide**

| If you have… | Read |
|---|---|
| 10 minutes | A1 (the pitch), A3 (the worked example), E1 (the numbers card) |
| 1 hour | All of Part A and Part B, then E1 |
| An evening | Everything, then answer Part F out loud without looking |

Contents

- **Part A — What it is**: the pitch, the problem, what a user sees, the architecture
- **Part B — How it works**: every stage in detail, the tech stack and why each piece was chosen
- **Part C — The data**: every dataset, how it was cleaned, what went wrong with it
- **Part D — How it was built and tested**: the timeline, evaluation, every result
- **Part E — Problems, lessons, limits**: what went wrong and what it taught, numbers card, glossary
- **Part F — Question bank**: ~120 questions, simple to hostile, with answers

---

# Part A — What it is

## A1. The pitch

**One sentence.** Pramana is a research assistant for Indian criminal law that reads a case's facts, works out which code applies (the old Indian Penal Code or the new Bharatiya Nyaya Sanhita), suggests the sections the facts disclose, **checks every section number against a database built from the real statute text before showing it**, and then finds precedent judgments, drafts defence counter-arguments and shows how past appeals on those sections ended, all running locally on a laptop with no cloud and no cost.

**Thirty seconds.** Lawyers in India have had a confusing year: on 1 July 2024 the Indian Penal Code (IPC, 1860) was replaced by the Bharatiya Nyaya Sanhita (BNS, 2023), and every section number changed. Theft was IPC 378/379; it is now BNS 303. Murder was IPC 302; BNS 302 is now about wounding religious feelings. An offence committed before that date is still tried under the IPC. AI chatbots make this worse because they invent or mix up section numbers. Pramana fixes the number problem structurally: a deterministic rule picks the code from the offence date, a small local language model proposes sections, and **nothing it proposes is shown as real unless it exists as a node in a citation graph built from the ingested statutes**. A second check asks whether the facts actually support each section. Then it pulls matching judgments, writes counter-arguments grounded only in verified material, and counts appeal outcomes.

**Two minutes** — add: it is retrieval-augmented generation (RAG), not a fine-tuned model; the embedder is BGE-M3, chosen by a measured bake-off over the legal-domain InLegal-Sbert; the corpus is about 88,000 chunks from 2,700 Supreme Court and High Court judgments plus both codes; the LLM is Qwen 3.5 4B running on Ollama on a 4 GB laptop GPU; the orchestration is a LangGraph state machine with a retry loop; the web interface shows each pipeline stage live. Evaluated honestly: the citation check has let **zero** invented sections through in every evaluation, but choosing the *right* sections is the weak part — on the published IL-TUR statute-identification benchmark it scores macro-F1 9.8 against 28.1 for the best supervised model.

## A2. The problem it solves

1. **The IPC → BNS transition.** From 1 July 2024 the BNS applies to offences committed on or after that date. Offences before it stay under the IPC, even if tried later. Section numbers were renumbered almost entirely. A lawyer in 2025–26 handles both codes at once. Some sections were merged (IPC 378 theft + 379 punishment → BNS 303), some split, some dropped (IPC 377 "against the order of nature", IPC 497 adultery), and the same number means different offences in the two codes (302 = murder in the IPC, a religious-feelings offence in the BNS).
2. **LLMs invent legal citations.** Studies of general chatbots and even commercial legal research tools in the US found frequent hallucinated or wrong citations (Dahl et al. 2024, "Large Legal Fictions"; Magesh et al. 2024 on legal research tools). This project saw it directly: asked what BNS 303 covers, the model confidently said a bomb-threat offence. BNS 303 is theft. (CLAUDE.md, 2026-09-25 entry.)
3. **Privacy.** A lawyer types a real client's facts. A free cloud model may train on prompts. So the system runs entirely on the user's machine.
4. **Cost.** A college project with zero recurring cost: no paid API, no paid hosting.

**Who it is for:** a lawyer or law student doing first-pass research on a criminal matter. **It is not** a judge, not legal advice, and not a replacement for reading the bare act.

## A3. The worked example (learn this by heart)

Input: *"The complainant parked his motorcycle outside his house at night. In the morning it was gone. CCTV shows the accused pushing it away down the lane and riding off. The accused had no permission to take it and did not return it."* Offence date **15 August 2024**.

1. **Router** (no AI): 15 Aug 2024 ≥ 1 Jul 2024 → **BNS**.
2. **Retrieval**: BGE-M3 encodes the facts; statute search plus "precedent votes" rank BNS sections. BNS 303 ranks **#1** of 14 candidates.
3. **Node 1** (LLM) proposes **BNS 303**.
4. **Node 2** (graph lookup, no AI): `bns:303` exists → **verified**.
5. **Node 2b** (LLM, two passes): quotes the facts for each ingredient → **supported**.
6. **Node 3**: no BNS theft case has reached an appeal court in the corpus (BNS 303 has **0** direct precedents), so it follows the verified mapping **BNS 303 ← IPC 378/379** and returns three distinct High Court theft judgments.
7. **Node 5** (pure SQL): disposal counts for appeals on those sections.
8. **Node 4** (LLM): one counter-argument — the prosecution must prove *dishonest intention*; mere movement is not enough. A final check confirms it targets a charged section, uses only supplied precedents, and quotes the facts verbatim.
9. The punishment card shows **up to 3 years, 1–5 years on a repeat conviction**, arrest/bail from the BNSS First Schedule.

Time: about 70 seconds live on the laptop. (`app/samples/motorcycle_theft.json`)

## A4. The architecture in one picture

```
OFFLINE, built once
  statutes (IPC JSON, BNS gazette PDF) ─┐
  SC judgments (PDF, 2023-26)          ├─► clean ► chunk ► metadata ─► BGE-M3 ─► ChromaDB (4 collections)
  HC judgments (NyayaAnumana subset)   ┘                    │
                                                            └─► citation graph (NetworkX): sections, cases, edges
  IPC↔BNS mapping (574 rows, reviewed)  ─► graph "maps_to" edges
  First Schedules (CrPC, BNSS)          ─► punishment / bail table
  outcomes (from graph edges)           ─► SQLite

RUNTIME, per case
  facts + offence date
   ► Stage 0  Offence-Date Router              (plain function)
   ► intake    court order? reduce it to facts (LLM, only if procedural)
   ► retrieval statute search + precedent votes, fused (RRF)   [BGE-M3 on GPU]
   ► guardrail nothing close enough? → "insufficient data" + review list, no LLM
   ► [hand the GPU from BGE-M3 to the LLM]
   ► LangGraph:
       Node 1  Statute Identifier (LLM, JSON)  → candidate_sections
       Node 2  Verifier (graph lookup)          → verified_sections / unconfirmed
          └─ retry edge: unconfirmed and retry_count < 2 → back to Node 1 with the rejection
       Node 2b Applicability judge (LLM ×2 + fixed rules) → supported / doubted
       Node 3  Precedent matcher  ┐ parallel
       Node 5  Outcome analytics  ┘ (SQL only)
       Node 4  Defence counter-arguments (LLM) + final verification pass
   ► FastAPI ► web page (or Streamlit), verified vs. doubted vs. rejected drawn differently
```

The single most important design idea: **the LLM only ever proposes; deterministic code decides what is real.** The router, the verifier, the rules, the analytics and every final check are ordinary code. The model is used where language understanding is unavoidable (reading facts, judging fit, writing arguments) and nowhere else.

---

# Part B — How it works, stage by stage

## B1. Stage 0 — the Offence-Date Router (`src/pipeline/router.py`)

- Plain Python, no AI. `route(date)` returns `"ipc"` if the date is before **2024-07-01**, else `"bns"`. A future date is rejected.
- Why deterministic: every later step depends on it. A wrong code poisons everything downstream (wrong statutes, wrong numbers). A date comparison can be tested exhaustively; a model cannot.
- **Straddling periods**: if an offence ran across the transition (e.g. a fraud from June to August 2024), `route_period` runs the pipeline **once per code** and warns the user. (This came from the hardening pass, register row 6.)
- The web page reads the date out of the facts with regular expressions only (`src/api/dates.py`): day-first Indian format, never guessed. If there is no date, several dates, or only a month, the page **asks** instead of guessing.
- Test: Phase 4 gate — 10 cases × 3 repetitions = **30/30** routed correctly, and the runner also checked that retrieval touched only that code's collections.

## B2. Intake — reading court orders (`src/pipeline/intake.py`)

- Problem found in Phase 6: real inputs are often court orders full of procedure ("learned counsel", "bail", "u/s 438 Cr.P.C."). That vocabulary dragged retrieval toward procedural sections and the model charged IPC 438 because the order mentioned *anticipatory bail under Section 438* — which is the CrPC, not the IPC.
- Fix: a deterministic test (≥ 3 of 22 procedural markers) decides if the input is an order. Only then, one LLM call restates the alleged facts, dropping procedure and section numbers. The restatement must share ≥ 60% of its content words with the original or it is discarded (protection against invented facts).
- `nofacts`: if the order states **no allegation at all** (adjournment, bail conditions), the system declines with `no_facts_stated` instead of charging procedure.
- Plain fact statements never trigger intake (0 of the project's fixtures do).

## B3. Retrieval (`src/retrieval/`)

**Embedder: BAAI/bge-m3**, 1024-dimensional, fp16 on the GPU, cosine similarity. Chosen by a bake-off (see C6).

**Four ChromaDB collections**: `ipc_sections`, `bns_sections`, `judgments_pre2024` (read as "IPC-era"), `judgments_post2024` ("BNS-era"). Judgments are routed by the **code they apply**, not the decision date — because an IPC appeal decided in 2025 is still IPC law, and mixing it into the BNS collection would recreate the "same number, two codes" error.

**Index-only views** (they exist only in the index, never replace corpus text):
- *Sub-section views*: BNS 3 "General explanations" is 4,765 characters; common intention is a 194-character sub-section 3(5). Embedded whole, it is buried. Each sub-section gets its own vector.
- *Counterpart views*: civictech's IPC text has no Illustrations; the gazette BNS text does, and Illustrations read like case facts. So each IPC section also gets a vector of its verified BNS counterpart's text.

**Two signals, fused:**
1. *Statute search*: facts vs. section text.
2. *Precedent votes*: find the 60 most similar judgment chunks; each **judgment** (not chunk) votes, weighted by similarity, for the sections it cites. In a BNS query, IPC judgments vote only through the verified mapping. Reason: case facts resemble other case facts far more than they resemble abstract statute definitions.
- Fused with **Reciprocal Rank Fusion**, `score = Σ 1/(60 + rank)`, the textbook k = 60. Every alternative tried (k = 10, CombSUM, interleaving, IDF-weighted votes) was worse on the dev set.

**Pair pooling** (`ranker.pool_pairs`, switch `pair`): the IPC often splits an offence into a definition (503 criminal intimidation) and a punishment section (506). Statute search finds the definition (it has the words), votes find the punishment (courts cite "506 IPC"). Fused as unrelated sections, each held half the evidence and the offence vanished from the list. Pooling gives both their best rank. This fixed "threat to kill charged as attempt to murder" at the retrieval level.

**What Node 1 reads**: the *dual list* — fused top 10 + statute-text top 10, about 14–16 sections, each with a 300-character excerpt. Non-chargeable sections (definitions, general exceptions) are excluded.

**The guardrail** (`src/pipeline/guardrail.py`): if the best *judgment* similarity is below **0.576**, the facts are too far from anything in the corpus; the LLM is not called. Calibrated on 25 criminal fact patterns (lowest 0.595) vs. non-legal text (highest 0.557); 0.576 is the midpoint. Two lessons: (1) best *statute* similarity was useless (a rent dispute scored 0.537, above 10 of 25 real crimes); (2) **no threshold separates civil from criminal facts** (0.60–0.63, inside the criminal range), so civil cases are handled by the model's reading, not the guardrail. Since 2026-10-03 the guardrail never returns a bare refusal: it shows the nearest sections for review, because it once falsely refused a real mischief case (similarity 0.555).

## B4. The VRAM handoff (an engineering detail examiners like)

The laptop GPU (RTX 3050 Ti) has **4 GB**. BGE-M3 at fp16 needs ~2 GB; qwen3.5:4b needs ~3.7 GB loaded. They cannot share the card. So, per case:
1. Ask Ollama to unload the LLM (`keep_alive: 0`) and **wait until `/api/ps` confirms** it is gone (Ollama otherwise keeps a model resident for minutes).
2. Load BGE-M3 on the GPU, encode the query, run statute search, precedent votes, **and prefetch the judgment pool Node 3 will need later** (because Node 3 runs after the LLM has taken the card back).
3. Free BGE-M3, then call the LLM.
Measured: pre-generation time 36 s (query on CPU) → 18 s (GPU after eviction), identical output.

## B5. Node 1 — Statute Identifier (`src/pipeline/nodes.py`)

- Input: the facts, the candidate list with excerpts, the code.
- Output: **JSON constrained by a schema** (Ollama compiles the schema into the decoding grammar), with `maxItems` and `maxLength` — without bounds the model once listed sections until the 5-minute request limit.
- Settings: `temperature 0`, `seed 0`, `think: false` (qwen3.5 is a "thinking" model; thinking tokens cost time), `num_predict` as a backstop that **raises** rather than silently truncating, `num_ctx` sized to the prompt (Ollama silently truncates over-long prompts).
- It also returns a **fact profile**: does it disclose an offence (and why), number of accused, injury grade (none/hurt/grievous hurt/death), dangerous weapon, whether harm was intended. Deterministic rules read this profile (B8).
- Prompt is "prima facie" framed: read the facts as a court framing a charge would.
- Self-negation filter: the model sometimes lists sections whose own reason begins "The facts do not disclose…". Those are withdrawn, never verified.

## B6. Node 2 — Verifier (`src/pipeline/nodes.py` + `src/graph/citation_graph.py`)

- **No AI.** `parse_citation` reads the model's text ("IPC 420", "Sec. 120-B", "303(2)"); `verify_section(g, code, section)` asks: is `code:section` a node in the graph? **The code is required — there is no "either code" mode**, because the union of the two codes is exactly the trap (BNS 420 does not exist; IPC 420 does).
- Rejection reasons: does not exist in this code; belongs to the other code; real but not chargeable (a definition); another Act / malformed.
- Hints: if the model cites an IPC number in a BNS case, the rejection names the verified BNS counterpart ("its BNS counterpart is BNS 303"), read off the graph.
- Definition → punishment: a verified IPC definition (405) is charged under its punishing section (406).
- Sub-section: only the section is verified, so the model's sub-section choice is dropped unless a rule chose it (the model picked 109(2) for attempt to murder, 318(1) definitions, etc.).

## B7. The retry loop (the LangGraph conditional edge)

- If Node 2 left anything unconfirmed **and** `retry_count < 2`, the graph goes back to Node 1 with the rejections.
- What made it work: the first version sent the feedback as a plain follow-up message, and the model re-proposed the same rejected `421` three times. Replaying its previous answer **as an assistant turn** and listing rejected numbers as **banned** fixed it: `421` ✗ → `378` ✗ (hint: BNS 303) → `303` ✓. (Phase 4 gate, 3/3.)
- Cap of 2 retries = at most 3 rounds, so a case can never loop forever.
- State keeps every round's proposals tagged with `round`, which is how the hallucination-catch rate is computed.

## B8. Node 2b — the applicability judge (`src/pipeline/applicability.py`, `offence_rules.py`)

"Verified" only means *the section exists*. BNS 66/67/68 (sexual offences) verify for a fraud case. So a second check asks whether the facts support each section.
- The model gets each section's text and the facts, and must **quote the facts** for the ingredients. A quote counts only if it is an exact substring of the facts (whitespace-normalised). Supported = model says it applies + ≥ 1 grounded quote + no missing ingredient named.
- **Two passes, section order reversed**, and "supported" requires **both** (self-consistency; the 4B model's verdict moved with the order of the list).
- **Advisory, not a gate** (decided 2026-09-30): as a gate it removed the right charge in 4 of 15 dev cases for a precision gain of only 38% → 42%. So nothing is deleted; doubted sections are shown in amber with the reason.
- **Fixed rules**, each with an ablation switch:
  - *Headcount*: unlawful assembly/rioting need 5+ people (IPC 141–149, BNS 189–191); joint liability and conspiracy need 2+. Decided from `accused_count`, never by the model.
  - *Liability rule*: 2+ accused acting together → propose IPC 34 / BNS 3(5); 5+ with a common object → IPC 149 / BNS 190. (Retrieval cannot find s34 — it ranked 146th — so the rule supplies it.)
  - *Injury rule*: (injury grade, weapon) → the hurt section (e.g. grievous + weapon → IPC 326 / BNS 118(2)).
  - *Death rule*: murder/homicide/dowry death need a death; if the profile says less, they are doubted.
  - *Attempt rule* (added 2026-10-15): an attempt to murder is never doubted merely because nobody died.
  - *Grievous consistency*: if the judge accepted 324 and doubted 326 on the very same weapon clause, the contradiction is overruled.
  - *Lesser-included*: a plain offence beside a supported aggravated form is shown as "included in" it (417 in 420, 324 in 326), not double-counted.

## B9. Node 3 — Precedent Matcher (`src/pipeline/precedents.py`)

- A judgment is precedent for a charge **only if the citation graph has an edge** from it to that section. Similarity decides only the *order*. (So similarity alone can never make something a "precedent".)
- For a BNS charge it also searches the verified IPC predecessor's judgments — essential, because BNS precedent barely exists yet (BNS 303: 0 direct; IPC 378/379: 72 and 159).
- Up to 3 per charge; companion judgments (same appeal filed under several numbers) are de-duplicated by 5-word-shingle overlap ≥ 0.6.
- The judgment neighbourhood (200 per collection) is fetched before generation (the VRAM handoff).

## B10. Node 5 — Outcome Analytics (`src/pipeline/analytics.py`)

- **Pure SQL, no LLM**, over `outcomes.sqlite` built offline from graph edges (2,699 cases, 16,493 case→section rows).
- Shows how appeals/petitions citing that section were **disposed of** (allowed / partly allowed / dismissed / other).
- **Not a conviction rate** — say this clearly if asked. An "allowed" appeal may be an accused winning or the State winning. NyayaAnumana's label is "petitioner succeeded", not "convicted".
- Suppressed below **5** judgments ("a percentage over three cases is noise presented as a statistic").
- Sentence ranges were **not** built: judgments mostly quote the *trial court's* sentence, which the appeal may have set aside.
- Runs in **parallel** with Node 3 in the LangGraph.

## B11. Node 4 — Defence counter-arguments (`src/pipeline/defense.py`)

- One LLM call, up to 4 arguments, each targeting one charge, attacking an ingredient the facts do not clearly establish. Input: facts, each charge's statute text, the judge's doubts, labelled precedents [P1]…, and (since 2026-10-15) the grievous-hurt definition when relevant.
- **Final verification pass** (deterministic): the target must be a charged section; every precedent label must be one actually supplied; the fact quote must be verbatim; any other section number mentioned must verify. Failures are attached as `issues` and the argument is marked unverified (shown, flagged).
- Prompt rules added 2026-10-15 after reading demo output: an Explanation or Illustration widens an ingredient, never adds a requirement; one argument per ingredient.

## B12. The web application (`src/api/`, `app/web/index.html`)

- **FastAPI** backend. `POST /analyze` (one-shot, used by Streamlit); `POST /jobs` + `GET /jobs/{id}` for the live view; `/samples`; `/section/{code}/{s}`; `/compare`; `/pdf`; `/ask`; `/summarise`; `/health`.
- **Live progress is real, not animated**: `src/pipeline/progress.py` emits start/done events with a summary of what each stage *actually produced*; the page draws the pipeline diagram and the "verification ledger" (section × retrieved rank × proposed by × graph × facts) from those events.
- Design: set like a law report (serif Spectral headings, IBM Plex Sans/Mono), one oxblood accent, light/dark themes; fonts are vendored so **the page makes no outside request** (a test pins this).
- Six saved samples replay instantly; any can be run live.
- **Lawyer tools** (each local, each graph-checked): bare-act drawer with punishment read from the section's own "shall be punished" clauses (and a separate repeat-conviction range); IPC↔BNS word diff; arrest/bail/court from the official First Schedules (BNSS: 465 rows; CrPC: 479 rows); PDF upload (PyMuPDF, no OCR); printable research memo; follow-up questions answered only from the report (every section mentioned is checked in the graph); precedent summaries (a key quote kept only if verbatim).
- A second frontend in **Streamlit** (`app/streamlit_app.py`, `run_demo.bat`) — the one CLAUDE.md originally specified — still works.

## B13. Tech stack, with the reason for each choice

| Layer | Tool (version) | Why this, and what was rejected |
|---|---|---|
| Language | Python 3.12.7 | ecosystem; matched an existing CUDA torch install on the machine |
| Deep learning runtime | PyTorch 2.6.0 + CUDA 12.4 | GPU embeddings; copied from an existing venv (same Python build) instead of a 2.6 GB download on a slow link |
| Embedder | **BAAI/bge-m3** via sentence-transformers 6.1 | won the bake-off: recall@3 0.533 vs InLegal-Sbert 0.20; 8,192-token context; multilingual |
| Vector store | **ChromaDB 1.5.9** (embedded, file-based) | no server, free, supports list metadata + `$contains` filters; 4 collections |
| Citation graph | **NetworkX 3.3** (in memory) | no server; the graph is small (3,632 nodes, ~17K edges); pickled, rebuilt in seconds |
| Orchestration | **LangGraph 1.2** | explicit state machine: typed shared state, a conditional retry edge, parallel branches (Nodes 3 ∥ 5) |
| LLM | **qwen3.5:4b** (Q4_K_M, 3.4 GB) on **Ollama 0.40.2** | local, free, 256K context, stronger reasoning than gemma3:4b at the same size; gemma3:4b left no VRAM for the KV cache. Fallback: qwen3.5:2b |
| LLM client | plain **httpx** to Ollama's REST API | no SDK dependency; exact control over `format` (JSON schema), `think`, `keep_alive` |
| PDF extraction | **PyMuPDF** | measured on an 18-page judgment: 0.02 s vs pypdf 0.15 s vs pdfplumber 0.84 s, slightly more complete |
| Backend | **FastAPI 0.141** + uvicorn | async-friendly, job endpoints, static files |
| Frontends | plain HTML/JS (no framework, no CDN) + **Streamlit 1.64** | offline; the HTML page gives full design control |
| Analytics store | **SQLite** (stdlib) | Node 5 is SQL only |
| Tests | **pytest** — 413 tests | fake embedders/LLMs make most tests run in seconds without a GPU |
| Data handling | pandas (vanga parquet metadata) | |
| Hardware | Windows 11 laptop, RTX 3050 Ti 4 GB, 16 GB RAM | the constraint that shaped many decisions |

**What it does not use, on purpose:** no cloud LLM (privacy), no fine-tuning (design rule), no paid API, no vector-DB server, no JS framework, no CDN.

---

# Part C — The data

## C1. Every source, what it is, how it was obtained

| Source | What | Size used | How obtained / trust |
|---|---|---|---|
| **IPC** | civictech-India `ipc.json` — 575 sections | ~1 MB | GitHub, structured JSON. Only the operative paragraph of each section; **IPC 304B (dowry death) was empty upstream** |
| **Official IPC consolidation (1997)** | Legislative Department text (Goa Police copy), sha256-recorded | used for patches | filled 304B and **completed 80 truncated sections** (300's clauses and Exceptions, 506's threat-to-kill limb, 307's life-convict clause…) under strict rules (C4) |
| **BNS** | Ministry of Home Affairs gazette PDF, Act 45 of 2023, digitally signed | 358 sections | **no trustworthy machine-readable BNS existed** — every GitHub copy was an unvetted hobby project; indiacode.nic.in timed out. So it was parsed from the gazette PDF |
| **Supreme Court judgments** | "vanga" open archive on AWS S3 (Mumbai), years 2023–2026, **English only** | 828 MB of PDFs, 2,533 + 214 judgments | digital-born PDFs with a text layer (no OCR). Regional-language tars deliberately skipped |
| **NyayaAnumana** | Hugging Face, gated (accepted terms + token). The 2020–2024 single-judgment test file | 1,827 judgments kept from 31,028 HC + SC rows | filtered to theft / hurt-assault / cheating / criminal breach of trust; read from the zip in place |
| **IPC↔BNS mapping** | built in-project: 574 IPC rows → BNS | 538 bridges, 36 "none" | proposed by a scorer, **every row reviewed** (by Claude, against gazette text — **not by a lawyer**) |
| **First Schedules** | BNSS (MHA gazette) and CrPC (CRPF copy, amended to 2013) | BNSS 465 rows / 288 sections; CrPC 479 rows / 395 sections | parsed by column position; cognizable / bailable / triable by |
| **IL-TUR** | ACL 2024 benchmark, gated; only LSI + PCR dev/test splits | 153.6 MB | for evaluation only; the 1.2 GB train splits were never downloaded |
| **Hanno-Labs indian-ipc-statute-identification** | ungated CC-BY-4.0, 14,876 Patna HC orders with sections masked | sampled 30–60 at a time | the substitute external benchmark while IL-TUR access was pending |

## C2. Final corpus sizes (`data/processed/build_report.json`)

| corpus | records |
|---|---|
| `statutes_ipc.jsonl` | 575 sections (one section per chunk) |
| `statutes_bns.jsonl` | 358 sections, every one, every marginal-note title |
| `judgments_pre2024.jsonl` (IPC-era) | 83,918 chunks (SC + 37,313 NyayaAnumana HC chunks) |
| `judgments_post2024.jsonl` (BNS-era) | 3,118 chunks |
| **total** | **87,969 chunks** |

Index: `ipc_sections` 1,113 vectors (sections + counterpart views), `bns_sections` 667 (sections + sub-section views), judgments ~84K + ~3K. ChromaDB on disk: 2.6 GB.

Citation graph: **933 section nodes** (575 IPC + 358 BNS), **2,699 case nodes**, **16,493 case→section `cites` edges**, **539 `maps_to` edges** (IPC→BNS).

**The striking fact about BNS data:** only a handful of judgments apply the BNS (6 BNS-only and 22 naming both codes at the first build; still few by 2026). No BNS theft case had reached the Supreme Court. That is why Node 3's IPC-predecessor bridge is not optional — it is where nearly all post-2024 precedent comes from.

## C3. Chunking and metadata

- **Statutes: one section per chunk** (rule from the project plan), plus index-only sub-section views.
- **SC judgments: by paragraph/holding, never fixed token counts.** Paragraphs are found by their numbers — with the rule that a paragraph number must be followed by whitespace (otherwise dates like `25.09.2015` at a line start opened 1,741 phantom paragraphs). Oversized "paragraphs" from failed splits (687 over 8,000 chars, largest **397,044**) are re-split at sentence boundaries above 4,000 chars.
- **NyayaAnumana: runs of whole sentences, ~1,200 chars**, because the source has no paragraphs at all (each judgment is one line, paragraph numbers stripped).
- **Every chunk has**: source, court, date (None for NyayaAnumana — its filename year is only a lower bound), `sections_involved`, doc id, collection.
- Validated against a fixed schema (`src/ingest/schema.py`); the writer re-reads its own line count from disk, and the gate cross-checks file counts against the build report (after a killed build once left a 0-line file that still "validated").

## C4. Cleaning the text — the defects found and fixed

These are the problems an examiner may probe; each was found by **reading** data, not by automated checks.

1. **Ligature padding**: PDFs render `fi` as one glyph plus a space (`ﬁ led` = "filed"). Hit **8.6% of judgment chunks** and exactly the important words (notification, definition, specified). Repair consumes exactly `len(expansion) − 1` spaces, and must run **before** whitespace collapsing.
2. **Running headers**: "SUPREME COURT REPORTS", party names, judge names inside **17%** of chunks. Stripped with a case-sensitive party-name rule so real prose naming the parties survives.
3. **Margin letters A–H** (SCR pinpoint letters) in 7.7% of chunks — stripped.
4. **BNS gazette glued words** ("ThisAct maybe called") — the PDF's own kerning, reproduced by every extractor; repaired by rule, never by guessing wording.
5. **BNS section heads without a space** (`104.Whoever`): a regex requiring `\.\s` silently lost 8 sections. Fix: each head must be exactly one more than the last.
6. **BNS titles are marginal notes** in a column that mirrors left/right by page. The first parser used the wrong coordinate (`x1` instead of `x0`), lost 11 titles **and glued them into other sections' text**, and a page-wrap rule gave 3 sections their neighbour's title (s97 "kidnapping" got "selling child for prostitution"). Rebuilt to assign notes by **document order**. All 358 titles now correct.
7. **IPC truncation**: civictech carries only the operative paragraph for ~80 sections. Completed from the official 1997 text **only where civictech's words are exactly the start of the official text (≥ 95%)**, because the 1997 text is *older* than civictech for anything amended since; the build fails if upstream changes under a patch.
8. **Bombay HC lost letters** after "f" ("frst", "ofence") — 140 repairs derived from the corpus's own vocabulary, each read.
9. **Devanagari mojibake** — 5–7 chunks, all inside Hindi quotations; a PDF font limitation, left as a warning.
10. **NyayaAnumana duplicates**: 1,863 exact duplicate rows; 49 SC rows that were copies of vanga judgments (detected by best-single-document containment ≥ 0.35).
11. **Per-court page furniture** in NyayaAnumana ("Downloaded on…", "Signature Not Verified Digitally Signed By…").

## C5. Extracting section citations — the hardest data problem

The citation graph is only as good as the case→section edges, which come from regex extraction of "Section N of the IPC" from judgment text.

- **Membership is not provenance.** CrPC 378 (appeal against acquittal) and IPC 378 (theft) share a number; so do CrPC 406/407 vs. IPC 406/407, CrPC 482 vs. IPC 482. **7,035 CrPC citations** were sitting in the corpus as IPC sections. Fix: read the words after the citation; drop it if it names the CrPC, the Evidence Act, "the Code", or any capitalised "X Act".
- **"120-B" must not become "120"** (conspiracy vs. concealing a design — both real, so a wrong edge looks verified).
- **Sub-sections leaked as sections** (`303(2)` produced s2).
- **Civil judgments**: a judgment naming *no* penal code was validated against both codes, turning every civil "Section N" into a penal edge (1,214 civil SC judgments). Now: no code named → no penal sections; and judgments naming no penal code are dropped from the corpus (1,682).
- **The big audit (hardening pass)**: reading 100 random edges showed **37 were not penal-code sections (63% precision)** — headnotes name the Act *before* the sections ("Evidence Act, 1872 – ss.4, 112"), bare "Section 482" is the CrPC, `S.2587/2011` is a suit number. After the fix and a corpus-derived "bare-citation trust" table (482: 2 penal uses vs 3,044 other), a **fresh** 100-edge sample was **96% correct**. Edges went 24,475 → 16,514.
- **Judgments citing both codes**: edges are taken only from citations that name their code.

## C6. The embedder bake-off (and why "domain model" lost)

- Plan said: use InLegal-Sbert (InLegalBERT, pre-trained on 5.4M Indian legal documents). A 2025 study (arXiv 2507.18455) had found general embedders match or beat it for Indian prior-case retrieval, so it was **measured, not assumed**.
- 15 hand-written fact patterns, each masked to its own code, recall@3 of the right section:

| model | dim | R@1 | R@3 | R@5 | MRR | peak VRAM |
|---|---|---|---|---|---|---|
| bhavyagiri/InLegal-Sbert | 768 | 0.133 | 0.20 | 0.333 | 0.223 | 0.56 GB |
| **BAAI/bge-m3** | 1024 | 0.067 | **0.533** | **0.60** | **0.295** | 3.26 GB (fp32) |

- InLegal-Sbert showed **hubness**: the same generic sections (IPC 443, 278; BNS 18, 52) topped almost every query.
- Gotcha: `law-ai/InLegalBERT` loaded through sentence-transformers does **not** error — it silently gets an untrained pooling head. Only `bhavyagiri/InLegal-Sbert` is the trained sentence model.
- Locked before mass ingestion, because changing embedder means re-embedding everything.

## C7. "Training" — there is none, and why

**Nothing was trained or fine-tuned.** This is the most likely trick question.
- The system is **retrieval-augmented generation**: a pre-trained embedder (BGE-M3) and a pre-trained LLM (Qwen 3.5 4B) are used as they are; knowledge comes from the retrieved statutes and judgments, and correctness comes from deterministic checks.
- Why not fine-tune: (1) the project rule "RAG, not fine-tuning" — the fix for a quality problem is better retrieval or prompting; (2) the 4 GB GPU cannot fine-tune a 4B model in any practical way; (3) laws change (they just did) — a fine-tuned model memorises old section numbers, whereas retrieval just needs the new statute ingested; (4) fine-tuning would not remove hallucination, while a graph check removes it structurally.
- **Be careful with one claim.** The project's founding notes say a fine-tuned Indian legal model (AALAP) scored worse than its base model on the AIBE bar exam. We could **not** confirm that number in the AALAP paper (arXiv 2402.01758 compares against gpt-3.5-turbo). Do not quote it as a fact; say "we chose RAG on design grounds and our measurements supported it".
- What *was* "learned" from data, without training: the guardrail threshold (calibrated), the embedder choice (bake-off), the bare-citation trust table (counted from the corpus), the chargeability table (from the codes' chapter structure), the First Schedules (parsed), the mapping (proposed by an overlap scorer, then reviewed).

## C8. The IPC↔BNS mapping

- Scorer: **overlap coefficient** `|A∩B| / min(|A|,|B|)` over content words. Two earlier scorers failed: `SequenceMatcher` on sorted words matched theft to selling-a-child; Jaccard scored the *right* pair (IPC 378 → BNS 303) at 0.056 because BNS sections inline all Explanations and Illustrations (233 content words vs 13).
- Spot-checked against 21 known pairs: 19 right; both misses flagged `low_evidence`.
- Then **all 574 rows reviewed**: 97 in-scope first (89 confirmed, 8 corrected — e.g. 302 → 103, 379 → 303), then 477 more (408 confirmed, 33 corrected, 36 "none"). A "none" must be **proved by absence** (phrase search of the whole BNS: no "thug", no "order of nature", no adultery offence).
- Failure modes found: "Punishment for X" sections (mostly boilerplate) and two sections **with the same title** (the right answer was usually the near-tied runner-up). `low_evidence` missed some errors (308 → 110 and 316 → 92 were unflagged).
- Special cases: IPC 124A (sedition) → BNS 152 noted as a *redrafted successor*, so its precedent is persuasive only; IPC 420 is compared with BNS 318(4); 304B → BNS 80 was missing and added on 2026-10-06.

## C9. Storage budget (the 20 GB discipline)

A self-imposed 20 GB ceiling (the disk actually had ~107 GB free), kept as discipline: smaller curated data embeds faster on 4 GB VRAM. Real numbers: venv 5.6 GB, ChromaDB 2.6 GB, raw data 1.2 GB (kept deliberately so extractor fixes could rebuild), processed 132 MB, Ollama model 3.4 GB, HF cache ~5 GB (half of BGE-M3's download is an unused ONNX folder). Regional-language judgment tars were never pulled; that alone avoided ~7× the planned judgment storage.

---

# Part D — How it was built, and how well it works

## D1. Timeline (from the git history: 100+ commits, 20 Sep – 15 Oct 2026)

| Dates | Phase | What happened |
|---|---|---|
| 20–21 Sep | **Phase 0, setup** | venv seeded by copying CUDA torch from an existing install (a 2.6 GB download on a ~30–700 KB/s link would take an hour); Hugging Face download failures diagnosed (Windows symlink privilege, stalled Xet transfer); embedder choice changed from "assume InLegal-Sbert" to "decide by bake-off"; Gemini was planned as primary LLM |
| 22 Sep | **Phase 1, data** | statute + SC ingestion; ligature and header repairs; **cloud LLM dropped** — generation fully local (privacy of client facts) |
| 24–26 Sep | Phase 1 cont. | 15 test cases written; BNS title fix; truncated-file guard; mapping review (97 rows); NyayaAnumana ingested; **7,035 CrPC citations removed from IPC edges**; judgments routed by code applied |
| 26 Sep | **Phase 2, retrieval** | BGE-M3 index; statute views; precedent votes + RRF; gate 11/15 dev (one short) + 10/10 held-out — accepted on 21/25 = 84% |
| 26 Sep | **Phase 3, citation graph** | `verify_section` (code required), `verify_case`, precedents, mapping bridge; **adversarial gate 20/20** |
| 27 Sep | **Phase 4, pipeline** | router, guardrail, Node 1, Node 2, retry loop; **gate PASS**: routing 30/30, adversarial retry 3/3. Data gaps filled: full 574-row mapping, 2026 judgments, broad-coverage test set |
| 27 Sep – 4 Oct | **Hardening pass** | owner's rule: no Phase 5 until earlier issues closed. Found the **63%-precision graph edges** (fixed to 96%); chargeability; applicability judge (two passes); headcount/liability rules; ablations; held-out sets 2–5; research-driven methods tried and rejected (cross-encoder reranker, sparse hybrid, Node 1 union, HyDE); GPU query encoding |
| 4 Oct | **Phases 5–7 MVP** | owner: "get the whole project done asap ... a working mvp". Nodes 3, 4, 5, FastAPI, Streamlit, demo cases. **Phase 6** on an ungated external set (IL-TUR still blocked) |
| 4–6 Oct | Intake; demo precision | court-order intake; lesser-included, injury, unanimous judge rules |
| 6 Oct | **Web interface** | chat-style page, live pipeline view, evidence map, lawyer tools, law-report redesign |
| 7–9 Oct | Accuracy pass | 80 IPC sections completed from official text; fact-free orders declined; scored on fresh orders |
| 9–14 Oct | **IL-TUR** | access granted; LSI dev 100 documents: macro-F1 9.8 |
| 14–15 Oct | Wrap-up and polish | launchers; precedent dedupe; repeat-conviction ranges; attempt rule; Node 4 grounding; samples refreshed; IL-TUR **test** run |

**Working method** (worth describing if asked "how did you manage the project"):
- one git branch per phase, merged only when that phase's written "Done when" gate was met;
- a single design record (`CLAUDE.md`) with non-negotiable rules and a "Known Gotchas" list — every corrected mistake was written down so it could not recur;
- **held-out test sets written before the change they test, and scored once** (the anti-overfitting protocol);
- every method change behind an **ablation switch** (`PRAMANA_ABLATE`) so it could be measured against the same code with only that change off;
- long evaluations made **resumable** (per-case checkpoint files), because the laptop's memory pressure killed them repeatedly.

**AI assistance (be ready for this question).** The code, data processing and documentation were developed with **Claude Code (an AI coding agent) as a pair-programmer**, directed by the project owner, who set the goals, constraints and decisions to delegate. Several "human" review steps (the mapping review, the gate reads) were explicitly delegated to the AI and are labelled as such in the data (`reviewer: "claude"`). Disclose this according to your institution's rules; the paper draft includes an acknowledgement.

## D2. The gates of the seven phases

| Phase | Gate (written before the work) | Result |
|---|---|---|
| 1 Data | processed JSON validates; 20 random chunks read, none truncated/malformed | passed — and the read found 3 more defects that validation had missed |
| 2 Retrieval | top-3 relevant in ≥ 12/15 test cases | 11/15 (one short) + 10/10 held-out; accepted; later re-scored 12/15 judged |
| 3 Graph | 100% on 10 real + 10 fabricated section numbers | **20/20** (fabricated include BNS 420 and BNS 498A — real IPC numbers, the union trap) |
| 4 Pipeline | 10 cases route correctly every time; adversarial case triggers and survives retry | **30/30**, **3/3** |
| 5 Full pipeline | motorcycle worked example end to end | done |
| 6 Evaluation | real numbers in `docs/evaluation_results.md`, reproducible by one script | done (`scripts/eval_phase6.py all`, `scripts/eval_lsi.py`) |
| 7 Frontend | motorcycle example works in the browser, no manual steps | done (`run_web.bat`) |

## D3. Metrics, explained simply

- **Recall@k (retrieval)**: fraction of test cases where a correct section is among the top *k* retrieved.
- **MRR**: mean of 1/rank of the first correct result.
- **"Right section charged"**: the case gets at least one correct section among its charges.
- **Precision**: of all sections charged, the fraction that are correct.
- **Micro-F1**: F1 over all (document, label) decisions pooled — dominated by frequent sections.
- **Macro-F1**: F1 computed per label, then averaged — every section counts equally, so rare sections matter as much as 302. IL-TUR LSI reports macro-F1.
- **Hallucination-catch rate**: of all citations Node 1 proposed, the share Node 2 rejected, and how many cases recovered within 2 retries; **leaked** = rejected citations that reached the charges (must be 0).
- **Definition = punishment** when scoring: IPC 378 (definition of theft) and 379 (punishment) count as the same offence on both sides.

## D4. The results — every number you might be asked for

### Citation verification (the core claim)
- Phase 3 adversarial set: **20/20**.
- Phase 6 hallucination-catch (`docs/evaluation_results.md` §3):
  - normal use (with retrieval), 30 real court orders, 94 proposals: **0 invented** — the model never proposed a non-existent number when shown candidates.
  - stress test (retrieval withheld), 15 dev cases, 68 proposals: **20 rejected (29%)** — mostly IPC numbers in BNS cases (420, 378–383, 465–468); **6/6 cases with a rejection recovered within 2 retries**; **0 leaked**.
- With retrieval context the model never took IPC-number bait ("Section 420" in a BNS-era complaint): 0/9.

### Retrieval
- Bake-off: BGE-M3 recall@3 0.533 vs InLegal-Sbert 0.20.
- Phase 2: dev 11/15 strict → 12/15 judged; held-out 10/10, later 8–9/10 after data changes; the list Node 1 actually reads contains a relevant section in **26/27** cases (the miss is common intention, supplied by rule).
- External (Patna HC orders): a charged section in the list for **157/300 (52%)**.

### End-to-end, project test sets (hand-written by Claude, not reviewed by a lawyer)
| set | right section charged | precision |
|---|---|---|
| dev (15) | 15/15 | 35% |
| held-out 2 (16) | 14/16 | 44% (57% with doubted set aside) |
| held-out 3 (10, criminal facts in civil-looking disputes) | 6/10 | 31% |
| held-out 4 (12) | 8/12 | 42% (59% with doubted set aside) |
| broad coverage (19) | 16/19 | 68% |
- Across three held-out sets the judge doubted **0 of 31** correct charges.
- Out-of-domain probes: **10/10** declined correctly (civil, tax, labour, family → "no offence disclosed"; recipe, cricket, gibberish → "insufficient data" before any LLM call).

### End-to-end, real court orders (Hanno-Labs, Patna HC)
| sample | right section charged | precision | procedural sections charged |
|---|---|---|---|
| first 30 | 12/30 (40%) | 14% | 25 times |
| ext0040–59, intake on | 13/20 (65%) | 24% | 3 |
| ext0060–89, current code | 13/30 (43%) | 21% | 1 |

### IL-TUR Legal Statute Identification (the published benchmark)
| | macro-F1 (all 100 labels) | micro P / R / F1 |
|---|---|---|
| **Pramana, dev split, 100 docs** | **9.8** (11.6 over the 84 labels with support, 95% CI 8.6–14.3) | 29 / 17 / 21 |
| Pramana, test split, 100 docs | *see `docs/evaluation_results.md` §7 (run 2026-10-15)* | |
| LeSICiN (supervised, published best) | 28.1 | |
| Hierarchical InLegalBERT (supervised) | 26.2 | |
| Hierarchical LegalBERT (supervised) | 21.7 | |
- **Far below the state of the art.** The baselines are trained on IL-TUR's 42K-document train split; Pramana is zero-shot. For calibration (a different Indian benchmark, ILSIC, EACL Findings 2026): **GPT-4.1 zero-shot reaches ~32% micro-F1 / 14.4% macro-F1**; Llama-3-8B and Gemma-3-12B 18–30% micro-F1. Pramana's 21 micro-F1 with a 4B local model sits in the range of 8–12B open models.
- Where the score goes: 30/100 docs got no charge (most state no allegation; ~5 were real facts wrongly declined); minor companion offences (504, 294, 323) rarely reach the candidate list (gold in list 99/290 = 34%); over-charging up the gravity scale (34, 307, 326 the commonest wrong charges); ~7% of gold labels are CrPC numbers.

### Speed
- ~1–3 minutes per live case (motorcycle ~70 s; knife ~145 s); IL-TUR documents ~85–150 s each.
- Pre-generation: 18 s with GPU query encoding (36 s on CPU).

## D5. What was tried and REJECTED (shows scientific method — examiners like this)

| idea | source of the idea | measured result | decision |
|---|---|---|---|
| InLegal-Sbert (domain embedder) | the original plan | R@3 0.20 vs 0.533; hubness | rejected |
| Hubness centring | literature | InLegal-Sbert 3→5, BGE-M3 8→6 | rejected |
| IDF-weighted votes, RRF k=10, CombSUM, interleaving | IR literature | all ≤ RRF k=60 | rejected |
| Cross-encoder reranker (bge-reranker-v2-m3) | COLIEE 2025 winners | dev recall@3 11 → 5 alone, 8 fused | rejected — rewards surface word overlap |
| BGE-M3 sparse / hybrid scoring | BGE-M3 paper (MIRACL +2.2) | top-3 11 → 7 fused | rejected — narrative facts vs abstract statutes share few words |
| Node 1 two-ordering union | COLIEE multi-LLM voting | relevant 20 → 22 of 31, precision 35% → 26% | switched off |
| HyDE (restate facts, then search) | literature | 11/15 = no change; theft cases drifted | off |
| Judge as a gate (delete doubted) | — | precision 38→42% but right charge lost in 4/15 | made advisory |
| Per-section judge calls | — | removed only 6/28 extras ("a small model says yes to anything in isolation") | kept batched |
| A companion-offence rule (504/323 questions) | IL-TUR dev analysis | macro-F1 on docs 36–100: 12.8 → 12.6 | closed, not merged |
| Fine-tuning | — | — | out of scope by design |

---

# Part E — Problems, lessons, limits

## E0. The challenges, grouped (with what each taught)

### 1. Hardware: a 4 GB GPU and 16 GB of RAM
- **Problem**: the embedder and the LLM cannot both fit in VRAM; the LLM itself does not fit fully (it runs ~52% CPU / 48% GPU), so it is slow.
- **Solution**: explicit VRAM handoff, verified eviction, prefetching Node 3's data while the embedder holds the card; fp16 embeddings (54–65 chunks/s vs ~10 at fp32; 84K chunks in ~21 min instead of ~2.5 h).
- **Problem**: long evaluations were **killed** repeatedly when free RAM fell under ~1 GB (Ollama ~4 GB + eval process ~4.7 GB + desktop apps).
- **Solution**: resumable runners with per-case checkpoints; `.bat` files to run outside the IDE; recording every interruption instead of hiding it.
- **Lesson**: constraints are design inputs. Several "clever" choices (a 4B model, prefetching, RRF instead of a reranker) exist because of the hardware.

### 2. A slow, unreliable network
- 18–700 KB/s, variable minute to minute; DNS failures for Ollama's blob host for ~2 hours; Hugging Face's Xet transfer stalled while plain HTTPS worked.
- **Lessons**: measure the host you are using, do not trust a quoted speed; Ollama pulls resume, Hugging Face downloads **never** resume (by design); disable symlinks on Windows (`HF_HUB_DISABLE_SYMLINKS`, not the `_WARNING` variant); set `HF_HUB_OFFLINE=1` or a model load can hang for 10 minutes on a metadata check.

### 3. Legal data is messy in ways automated checks do not see
- Ligatures, headers, glued words, wrong titles, truncated sections, CrPC numbers posing as IPC numbers, suit numbers posing as sections, duplicated rows, a 397,044-character "paragraph".
- **Lesson (the single most repeated one)**: *automated checks confirm the shape; only reading the content shows it is wrong.* Schema validation, zero duplicates and zero encoding errors all passed while 8.6% of chunks had broken words and 37% of graph edges were wrong.
- **Lesson**: audit precision with a **fresh** random sample — the sample that shaped a fix cannot also certify it (63% → 96% was measured on a new sample).

### 4. The two codes, renumbered
- Same number, different offence; merged and split sections; definitions vs punishment sections in the IPC but not the BNS.
- **Lessons**: never validate a citation against the union of both codes; never *score* retrieval against the union either; route judgments by the code they apply, not by date; treat a definition and its punishing section as one offence when scoring.

### 5. The small LLM's behaviour
- Unbounded JSON never stops → schema bounds. Retry feedback ignored → replay as an assistant turn + banned list. Lists sections it has itself ruled out → self-negation filter. Hyper-literal applicability judging ("a fracture is not shown to be grievous hurt") → prima facie framing, quotes-first prompt, deterministic rules. Verdicts change with the order of the list → two passes reversed. Picks wrong sub-sections → cite the verified section. Runs are not reproducible run to run even at temperature 0 → re-run demos twice, and score on enough cases to see noise.
- **Lesson**: the model is good at reading and writing, unreliable at bookkeeping. Move every decision that *can* be a rule into code; keep the model for language.

### 6. Verified ≠ applicable (the central quality problem)
- A graph check proves existence, never fit. The system over-charges: extra sections that exist but do not apply (precision 20–45% on most sets).
- Mitigations: applicability judge (advisory), headcount/death/attempt/injury/lesser-included rules, chargeability filter. Precision on dev rose modestly (33% → 39%); "doubted" is a useful signal (on IL-TUR dev, 135 of 220 wrong charges were doubted vs 29 of 71 right ones).
- **Lesson**: in legal AI, the asymmetric costs matter. Missing a real offence (or falsely declining a case) is worse than an extra flagged section, so the judge informs rather than deletes.

### 7. Evaluation honesty
- Hand-written fixtures flatter the system (60–100%) vs real orders (40–65%) vs the benchmark (macro-F1 9.8).
- The benchmark (IL-TUR) was gated and access took weeks; a substitute ungated set was used meanwhile and labelled as such.
- **Lessons**: write held-out sets before the change; score once; compare against the same code with only the switch flipped; report setbacks (the broad-coverage setback is in the record as "a SETBACK, recorded as is").

### 8. Safety: false declines
- Two real cases were wrongly declined (a threat to burn a family alive called "a civil dispute"; a mischief case refused by the guardrail).
- Fix: **no bare refusal on any path** — when the system thinks there is no offence or too little data, it still shows the nearest sections for review.

## E1. The numbers card (memorise these)

| what | number |
|---|---|
| Transition date | **1 July 2024** (offence date decides) |
| Sections | IPC **575**, BNS **358** |
| Judgments in corpus | ~2,700 (SC 2023–26 + 1,827 HC from NyayaAnumana) |
| Chunks | **87,969** |
| Graph | 933 section nodes, 2,699 case nodes, 16,493 cites edges, 539 maps_to edges |
| Mapping | 574 IPC rows: 538 bridges, 36 none |
| Embedder | BGE-M3, 1024-d; bake-off R@3 **0.533 vs 0.20** |
| LLM | qwen3.5:4b, 3.4 GB, local Ollama |
| GPU | RTX 3050 Ti, **4 GB** |
| Guardrail | best judgment cosine **0.576** |
| Retry cap | **2** retries (3 rounds) |
| Judge | 2 passes, unanimous, advisory |
| Graph gate | **20/20** |
| Routing gate | **30/30** |
| Edge precision | **63% → 96%** after the audit fix |
| Hallucinations leaked | **0** in every evaluation |
| Stress test | 20 of 68 proposals rejected, 6/6 recovered |
| IL-TUR LSI dev | macro-F1 **9.8** vs **28.1** supervised SOTA |
| Tests | **413** passing |
| Time per case | ~1–3 min |
| Cost | **₹0 recurring** |

## E2. Limitations (say these before you are asked)

1. **Precision**: it proposes too many sections; the judge flags many but not all.
2. **Not state of the art** on IL-TUR statute identification (zero-shot vs supervised).
3. **Narrow corpus**: Supreme Court 2023–26 plus a High Court subset filtered to theft/hurt/cheating/breach of trust. Offences outside those families have fewer close judgments.
4. **Very little BNS case law exists**, so post-2024 precedent comes almost entirely through IPC predecessors — persuasive, and not always identical law.
5. **Legal review**: the mapping, the fixtures' answer keys and the gate judgements were done by an AI, not a lawyer.
6. **Analytics are appeal disposals**, not conviction rates; no sentence ranges.
7. **Not deterministic** run to run despite temperature 0.
8. **Speed**: minutes per case on a laptop.
9. **English only**; PDFs without a text layer (scans) are not read (no OCR).
10. **Prior-case retrieval** (Node 3) is not evaluated on a benchmark (IL-TUR PCR was downloaded but not run).

## E3. Future work (good answers to "what would you do next?")

- Lawyer review of the mapping and the test keys; then a lawyer-graded evaluation of Node 4's arguments.
- Run IL-TUR PCR for Node 3; extend the corpus to more High Courts and offence families.
- A precision layer trained on charge data — allowed only if the project's no-fine-tuning rule is revisited; a small classifier over (facts, section) pairs is the obvious candidate.
- Larger local model when hardware allows (7–8B fits a 8 GB GPU), or qwen3.5:2b for speed.
- OCR for scanned FIRs; Hindi input.
- Sentence extraction that ties each sentence to the court that imposed it and the final disposal.

## E4. Glossary

**Legal**
- **IPC** — Indian Penal Code, 1860; the substantive criminal code until 30 June 2024.
- **BNS** — Bharatiya Nyaya Sanhita, 2023 (Act 45 of 2023); in force from 1 July 2024.
- **CrPC / BNSS** — Code of Criminal Procedure 1973 / Bharatiya Nagarik Suraksha Sanhita 2023 (procedure). **BSA** replaced the Evidence Act.
- **First Schedule** — the CrPC/BNSS table saying, for each offence, the punishment, whether it is cognizable (police may arrest without warrant), bailable, and which court tries it.
- **Section / sub-section / Explanation / Illustration** — Explanations and Illustrations clarify or widen a section; they are not extra requirements.
- **Definition vs punishment section** — IPC 378 defines theft, 379 punishes it; the BNS merged them (303).
- **Common intention** — IPC 34 / BNS 3(5): several people acting together in furtherance of a shared intention are each liable.
- **Unlawful assembly / rioting** — 5 or more persons (IPC 141–149; BNS 189–191).
- **Grievous hurt** — the closed list in IPC 320 / BNS 116 (fracture, endangering life, etc.).
- **Lesser-included offence** — a plain offence contained in an aggravated one (cheating 417 within 420).
- **Prima facie** — on the face of it; the standard at the charge-framing stage.
- **Precedent** — a decided judgment applying the section.
- **Disposal** — how an appeal/petition ended (allowed, dismissed…).
- **SCR** — Supreme Court Reports.

**Machine learning / IR**
- **RAG** — retrieval-augmented generation: retrieve relevant text, give it to the LLM.
- **Embedding** — a vector representing a text's meaning; similar texts have close vectors (cosine similarity).
- **Hubness** — in high-dimensional spaces some points are nearest neighbours of almost everything; here, the same generic sections topped every query.
- **RRF** — reciprocal rank fusion: combine rankings by summing 1/(k + rank).
- **Cross-encoder reranker** — a model that scores a (query, document) pair jointly; slower, often more accurate; here it was worse.
- **Self-consistency** — ask more than once and combine answers.
- **Zero-shot** — no task-specific training.
- **Ablation** — switch one component off to measure its contribution.
- **Held-out set** — test data not used while building; scored once.
- **Macro / micro F1** — see D3.
- **fp16** — 16-bit floating point; half the memory of fp32.
- **Quantisation (Q4_K_M)** — storing LLM weights in ~4 bits so a 4B model is 3.4 GB.
- **JSON-schema constrained decoding** — the runtime only allows tokens that keep the output valid against the schema.
- **LangGraph** — a library for building LLM workflows as state machines (nodes, edges, conditional edges).

## E5. Running the project (and what to do if the demo breaks)

- Start: double-click `run_web.bat` → opens `http://127.0.0.1:8000/`. It starts Ollama if needed.
- Before a demo: close Chrome tabs and VS Code (memory); open each sample once; run your live case once.
- If a live run fails at Node 1: Ollama is not running or the model is missing → `ollama list` must show `qwen3.5:4b`. Saved samples still work without Ollama.
- If the page looks old after an update: hard refresh (Ctrl+F5).
- Rebuild from raw data: `build_corpus.py` → `build_index.py` (~25 min GPU) → `build_graph.py` → `build_outcomes.py`. Tests: `venv\Scripts\python.exe -m pytest tests -q`.
- Benchmark: `scripts\eval_lsi.py --split dev --n 100` (~2.5 h, resumable).

---

# Part F — Question bank

Answer out loud, then check. **Bold** marks the phrase that should be in your answer.

## F1. Basics

1. **What is Pramana?** A local research assistant for Indian criminal law: from facts and an offence date it picks the code, proposes sections, **verifies every section against a citation graph built from the real statutes**, checks the facts support them, finds precedents, drafts defence arguments and shows appeal outcomes.
2. **Why the name?** *Pramāṇa* is Sanskrit for "means of valid knowledge / proof" — the system's point is that every citation is proven against data.
3. **Who is the user?** A lawyer or law student doing first-pass research. Not a client, not a judge.
4. **What input does it need?** A description of the facts, and the offence date (typed, or read from the text; the page asks if unclear). It can also take a pasted court order or a PDF.
5. **What does it output?** Charges marked verified/supported, doubted (with reason), included-in, or rejected; precedents; counter-arguments; outcome counts; punishment and bail; a printable memo.
6. **Does it need the internet?** No. Everything runs on the laptop; no API key, no account.
7. **What does it cost?** Nothing recurring. All tools and models are free and local.
8. **What is the BNS and why does it matter here?** The Bharatiya Nyaya Sanhita, 2023, replaced the IPC for offences on or after **1 July 2024**, and renumbered nearly every section. Lawyers now work with both codes.
9. **Give an example of renumbering.** Theft: IPC 378/379 → BNS 303. Murder: IPC 302 → BNS 103; BNS 302 is a different offence (wounding religious feelings). Cheating: IPC 420 → BNS 318(4).
10. **Walk me through the worked example.** (A3) motorcycle, 15 Aug 2024 → BNS → 303 retrieved #1 → proposed → verified → supported → precedents via IPC 378/379 → argument on dishonest intention.

## F2. Motivation and design choices

11. **Why not just use ChatGPT?** It invents or mixes up section numbers (our own model said BNS 303 was a bomb-threat offence), it does not know which code applies by date, and a lawyer's client facts would leave the machine.
12. **What is the single most important design idea?** **The LLM only proposes; deterministic code decides what is real.**
13. **Why RAG instead of fine-tuning?** Laws change (they just did) — retrieval needs the new text ingested, a fine-tuned model would need retraining; fine-tuning does not stop hallucination, a graph check does; the 4 GB GPU cannot fine-tune; and the project rule is that quality problems are fixed by better retrieval or prompting.
14. **Did you train any model?** **No.** Pre-trained BGE-M3 and Qwen 3.5 4B are used as they are. What was "fitted" to data: the guardrail threshold, the embedder choice (bake-off), the citation-trust table, the mapping (scored then reviewed).
15. **Why local generation only?** Privacy: a lawyer types a client's real facts, and free cloud tiers may train on prompts. Also no key, no cost, works offline.
16. **Why a 4B model and not something bigger?** It is the largest that runs at usable speed on a 4 GB GPU (and even it runs half on CPU). 7B+ models don't fit.
17. **Why Qwen and not Gemma or Llama?** gemma3:4b left no VRAM for the context cache on this card; qwen3.5:4b is similar size, stronger at reasoning, has a 256K context, and supports JSON-schema output well through Ollama.
18. **Why is the router not an AI?** It is a date comparison; making it a model would add risk with no benefit, and every downstream step depends on it. It is tested exhaustively.
19. **Why LangGraph?** The pipeline is a state machine with a **conditional retry edge** and **parallel branches** (Nodes 3 and 5); LangGraph gives typed shared state and those edges explicitly.
20. **Why NetworkX and not a graph database?** The graph is small (~3.6K nodes, ~17K edges), fits in memory, rebuilds in seconds; a database server would add setup with no gain.
21. **Why ChromaDB?** Embedded and file-based (no server), free, supports metadata filters on list fields.

## F3. Data

22. **Where does the data come from?** IPC: civictech JSON (+ official 1997 text for completions); BNS: the MHA gazette PDF; Supreme Court judgments 2023–26 from the open "vanga" S3 archive; High Court judgments from NyayaAnumana (gated HF dataset), a filtered subset; mapping and schedules built in-project.
23. **How big is it?** 575 IPC + 358 BNS sections; ~2,700 judgments; **87,969 chunks**.
24. **Why not all of NyayaAnumana (700K cases)?** Disk and embedding time on a 4 GB GPU, and relevance: a curated subset (theft, hurt, cheating, breach of trust) matched the test cases.
25. **Why only 2023–2026 SC judgments?** They straddle the transition, giving both IPC and BNS judgments; earlier years add size, not BNS coverage.
26. **How did you get the BNS text?** Parsed the official gazette PDF — no trustworthy machine-readable BNS existed. Titles are marginal notes, which needed geometry-based parsing.
27. **How were judgments chunked?** By paragraph/holding (paragraph numbers), never fixed token windows; oversize splits re-cut at sentences; NyayaAnumana (no paragraphs) in ~1,200-char runs of whole sentences.
28. **Why not fixed-size chunks?** A legal holding cut in half loses its meaning; paragraph boundaries are the natural unit of reasoning in a judgment.
29. **What metadata does each chunk carry?** Source, court, date, sections involved, document id.
30. **What was the hardest data problem?** Extracting *which law* a "Section N" belongs to. CrPC and IPC share numbers; headnotes put the Act before the sections; suit numbers look like sections. The graph's edges were only **63%** correct until an audit; after the fix a fresh sample was **96%**.
31. **How did you map IPC to BNS?** An overlap-coefficient scorer proposed a BNS section for each of 574 IPC sections; every row was then reviewed against the gazette text: 538 bridges, 36 "none" (proved by phrase search, e.g. adultery, s377).
32. **Who reviewed the mapping?** The AI assistant (Claude), against the official text, row by row — **not a lawyer**. Each row records `reviewer: "claude"`. A lawyer review is listed as future work.
33. **What is NyayaAnumana's label and why can't you use it as conviction rate?** 1 = the appeal/petition was allowed, 0 = rejected. It is petitioner success — a 0 can be a refused bail or a failed State appeal.
34. **How did you clean the PDFs?** Ligature repair (8.6% of chunks), header/footer and margin-letter stripping, glued-word repair for the gazette, title reconstruction, sourced patches for truncated IPC sections. (C4)
35. **Did you delete raw data after processing as planned?** No — deliberately kept (~1 GB): extractor bugs kept being found, and every fix needed a full rebuild; NyayaAnumana is gated and the link is slow.

## F4. Retrieval

36. **Which embedding model and why?** BGE-M3, by a measured bake-off: recall@3 **0.533 vs 0.20** for the legal-domain InLegal-Sbert on 15 test cases.
37. **Isn't a legal-domain model supposed to be better?** That was the assumption; a 2025 study found otherwise for Indian case retrieval, and our measurement agreed. InLegal-Sbert showed **hubness** — the same generic sections topped every query.
38. **What are "precedent votes"?** The most similar judgment chunks vote (weighted by similarity, one vote per judgment) for the sections those judgments cite. Facts resemble other facts more than abstract statute text.
39. **How are the two signals combined?** Reciprocal rank fusion, k = 60. Alternatives were measured and were worse.
40. **What does Node 1 actually see?** ~14–16 candidate sections: fused top 10 plus statute-text top 10, each with an excerpt; definitions and general exceptions excluded.
41. **Why did you add sub-section views?** Common intention is a 194-character sub-section inside BNS 3's 4,765 characters; embedded whole it ranks 155th.
42. **What is pair pooling?** The IPC splits definition (503) and punishment (506); text finds one, votes find the other; pooling gives both the better rank so the offence is not lost.
43. **Why didn't you use a reranker?** Tried the standard cross-encoder (bge-reranker-v2-m3): recall@3 fell from 11/15 to 5/15. It rewards surface word overlap (a theft at a house ranked house-breaking first).
44. **Why not hybrid (keyword + dense)?** Tried BGE-M3's sparse scores: worse (11 → 7). Narrative facts and statute text share few words.
45. **What is the guardrail?** If the best judgment similarity is below 0.576, the LLM is not called and the user gets "insufficient data" plus the nearest sections for review.
46. **How was 0.576 chosen?** Midpoint between the highest non-legal input (0.557) and the lowest real criminal fact pattern (0.595).
47. **Can the guardrail tell civil from criminal?** **No** — civil facts score 0.60–0.63, inside the criminal range. That is the model's job; the guardrail only stops non-legal text.
48. **Why does retrieval miss common intention (s34)?** It is an abstract liability rule; the facts' dominant meaning is the violence. s34 ranked 146th. A rule supplies it from the number of accused acting together.

## F5. Verification and the citation graph

49. **What is in the graph?** Section nodes (IPC, BNS), case nodes (judgments), `cites` edges (case → section, from extraction), `maps_to` edges (IPC → BNS, verified mapping only).
50. **What does "verified" mean exactly?** The section exists as a node **in the code that applies** to this case. Nothing more.
51. **Why must the code be specified?** Because the union of both codes is the trap: "BNS 420" doesn't exist but "IPC 420" does; checking against both would pass it.
52. **Can the LLM bypass verification?** No. The report's charges are built only from `verified_sections`; rejected ones go to a separate `unconfirmed` field and are drawn struck-through. A test pins that rejected citations never reach charges ("leaked = 0").
53. **What happens when a citation is rejected?** The reason is recorded; if retries remain, Node 1 is asked again with its previous answer replayed and the rejected numbers banned, plus a hint (e.g. the BNS counterpart).
54. **Why only 2 retries?** Enough to recover in every measured case (6/6), and it bounds latency; the cap guarantees termination.
55. **What did the Phase 3 gate test?** 10 real and 10 fabricated section numbers, including BNS 420 and BNS 498A (real IPC numbers), repealed IPC 13, and patched 304B — **20/20**.
56. **What is the hallucination-catch rate?** In normal use the model proposed 0 non-existent sections in 94 proposals. With retrieval withheld (stress), Node 2 rejected **20 of 68 (29%)**, all cases recovered within 2 retries, **0 leaked**.
57. **So the hallucination problem is solved?** The **citation-existence** problem is solved structurally. The **applicability** problem — real sections that don't fit the facts — is not; that is the main weakness.

## F6. The LLM nodes, the judge and the rules

58. **How do you get reliable JSON from a 4B model?** Ollama's JSON-schema constrained decoding, with `maxItems`/`maxLength` bounds; temperature 0, a seed, thinking disabled, a token cap that raises an error instead of truncating.
59. **What is Node 2b?** The applicability judge: for each verified section, the model must quote the facts for its ingredients; a quote counts only if it appears verbatim. Two passes with the order reversed; supported only if both agree.
60. **Why two passes?** The 4B model's verdict changed with the order of the list; requiring agreement of both orders makes "supported" more trustworthy.
61. **Why is the judge advisory and not a filter?** As a filter it deleted the right charge in 4 of 15 dev cases for a small precision gain. Missing a real offence is the worse error, so doubts are shown, not enforced.
62. **Name the deterministic rules.** Headcount (5+ for rioting, 2+ for joint liability), liability (propose 34 / 3(5)), injury grade (→ hurt section), death (murder needs a death), attempt (attempt to murder needs no death), grievous consistency, lesser-included, chargeability (definitions are never charges), definition→punishment.
63. **Why rules instead of better prompts?** Counting people or checking whether someone died is bookkeeping, which a small model does unreliably and code does perfectly. Each rule has an ablation switch and was measured.
64. **Give an example of the model being wrong and a rule fixing it.** The judge doubted attempt to murder because "death" was missing — but an attempt is exactly the case where death did not occur. The attempt rule overrules only that objection.
65. **How does Node 4 avoid inventing case law?** It may only cite labels [P1]… of precedents actually supplied; a final deterministic pass checks each label, each quote (must be verbatim from the facts) and each section mentioned (must verify); failures are flagged on the argument.
66. **How are precedents chosen?** Only judgments with a graph edge to the charge; ranked by similarity to the facts; for BNS charges also via the IPC predecessor; near-duplicate companion judgments merged.
67. **What does Node 5 compute?** SQL counts of how appeals/petitions citing the section were disposed of, suppressed below 5 judgments. No LLM.
68. **Why are Nodes 3 and 5 parallel?** Both depend only on the verified sections and not on each other; LangGraph runs them as parallel branches.
69. **What is the "intake" step?** For pasted court orders: a deterministic marker test, then one LLM call to extract only the alleged facts, checked for word overlap with the original.

## F7. Evaluation

70. **How did you evaluate?** Five layers: per-phase gates; hand-written dev and held-out sets (scored once each); out-of-domain probes; an external set of real Patna HC orders; and the published IL-TUR LSI benchmark.
71. **What is IL-TUR?** The Indian Legal Text Understanding and Reasoning benchmark (ACL 2024). LSI = legal statute identification: given facts, predict the IPC sections (100 labels).
72. **What did you score?** Macro-F1 **9.8** on 100 dev documents (micro-F1 21), against **28.1** for the best supervised model (LeSICiN).
73. **Why so far below?** The baselines are **trained on IL-TUR's 42K training documents** and its label conventions; Pramana is zero-shot with a 4B local model. Many documents state no allegation; minor companion offences (504, 323) rarely reach the candidate list; it over-charges grave sections (307, 326).
74. **Is that a fair comparison?** It is the standard metric on the standard split, so it is reported; but it compares a supervised classifier to a zero-shot system. A closer calibration: on the ILSIC benchmark GPT-4.1 zero-shot gets ~32% micro-F1 and 8–12B open models 18–30%; Pramana's 21 is in that band.
75. **Did you tune on the test set?** No. Decisions were made on dev; the test split was run once at the end (2026-10-15).
76. **What is your precision and why is it low?** About 20–45% depending on the set. The model over-proposes real-but-inapplicable sections, and the IL-TUR/charge-sheet labels themselves often list several companion sections the facts don't spell out.
77. **Your hand-written test sets were written by an AI — isn't that circular?** They flatter the system (60–100% vs 40–65% on real orders), which is exactly why the external set and the benchmark were added and are the numbers we lead with.
78. **How do you know results aren't noise?** Small sets are noisy — we say so: on 20 cases, one or two flips are within run-to-run variation (we saw a case flip with identical input). We report confidence intervals on IL-TUR (8.6–14.3 for the supported-label macro-F1) and avoid claims from one-case differences.
79. **What is an ablation and did you do one?** Turning one component off with everything else the same. Yes: every hardening change has a `PRAMANA_ABLATE` switch; e.g. the fact profile off lost common intention (recall 14 → 12) and raised extras (30 → 37).
80. **What did you NOT evaluate?** Prior-case retrieval on a benchmark (IL-TUR PCR); the legal quality of counter-arguments (no metric; read by hand); speed under load.

## F8. Hostile and twisted questions

81. **"So it's just ChatGPT with extra steps?"** No — the model never decides what is real. A deterministic router picks the code, a graph lookup verifies every number, rules handle counting and logic, analytics are SQL, and a final pass checks the generated arguments. Zero invented sections have reached a report in any evaluation.
82. **"Your score is a third of the state of the art. Why should anyone use this?"** It is not competing as a classifier. It is a research aid whose citations are guaranteed to exist in the right code, which runs privately on a laptop, and which explains each section with the statute text, punishment, bail and precedent. On accuracy of section *choice* it is weak, and we say so.
83. **"If the model can't choose sections well, what's the point of verification?"** Verification removes the most dangerous failure — a confident, non-existent or wrong-code citation — so what remains is a reviewable list rather than a fabricated one.
84. **"Why should I trust an AI-reviewed mapping?"** You should treat it as unreviewed by a lawyer. Its method is documented: every change located by an exact phrase match in the gazette text, every "none" proved by absence. It is on the future-work list for lawyer review.
85. **"Isn't the guardrail threshold overfitted to 35 examples?"** It is a midpoint in a measured gap on 35 inputs, and it is only used to stop *non-legal* text; it never refuses a case outright (it always shows the nearest sections). We documented one false refusal and changed the design because of it.
86. **"Temperature 0 means deterministic, so why do your demos vary?"** We measured that it does vary (the same group-assault facts gave different extra sections on three runs), even with temperature 0 and a fixed seed. The likely cause is numerical: the model runs split across GPU and CPU, and floating-point results can differ slightly between runs, which can flip a near-tied token. We did not prove the cause; we handle the effect by re-running demo cases and by not trusting one-case differences in evaluations.
87. **"Your 'precedents' for BNS theft are IPC judgments — that's wrong law."** For offences re-enacted in identical terms (IPC 378 → BNS 303) the IPC precedent remains good guidance; the report labels it "through the IPC predecessor". For redrafted sections (124A → 152) the mapping notes that precedent is persuasive only.
88. **"Can a lawyer rely on this in court?"** No. It is a research aid; the page says so. Every section links to its bare text for the lawyer to read.
89. **"What if the offence date is wrong?"** Then the code is wrong; the router can only be as right as the date. That is why the page asks when it cannot read a single clear date, and handles periods straddling 1 July 2024 by running both codes with a warning.
90. **"Why not fine-tune — wouldn't 28 F1 be easy then?"** Possibly better on IL-TUR, but it would memorise one benchmark's label conventions and today's section numbers, cannot run on this hardware, and would not remove hallucination. It was excluded by design; we report the cost of that choice.
91. **"The LLM is 4B — isn't it too small for law?"** It is small, which is why the system leans on retrieval and rules; where it matters most (citations), its output is checked. The measured weakness (applicability, precision) is exactly where size shows.
92. **"How do you know the extraction of sections from judgments is right?"** We audited it: 100 random edges read by hand, 63% correct; fixed; a *new* random 100 read: 96%. Each audited string is now a test.
93. **"Didn't you just tune until the numbers looked good?"** The protocol prevents that: held-out sets were committed before the changes they test and scored once; setbacks are recorded (the broad-coverage set got worse after hardening, and that is in the report).
94. **"Your analytics show 70% of appeals allowed — so 70% acquittal?"** No. It is disposal of appeals/petitions — an allowed appeal can be a State appeal, a bail plea or a quashing. The page labels it "not a conviction rate".
95. **"What happens to my client's data?"** It never leaves the machine. No network calls at runtime except to the local Ollama server; the web page loads no external resources (a test pins this).
96. **"Who wrote the code?"** Built with Claude Code as an AI pair-programmer under the owner's direction. (Answer honestly and per your institution's policy; know the design reasons in this guide, because that is what an examiner will probe.)
97. **"What's the most embarrassing bug you found?"** The graph's edges were 37% wrong for weeks — CrPC procedure numbers and other Acts counted as IPC offences. It was found only by reading 100 edges by hand.
98. **"What would break if someone typed a Hindi FIR?"** The embedder is multilingual, but the corpus, prompts and checks are English; results would be poor. English only is a stated limitation.
99. **"Isn't 'verified' misleading to a lay user?"** That is why the page separates three levels: verified (exists), supported (the facts were quoted for it on both readings), doubted (exists but the check found a gap, with the reason) — and draws them differently.
100. **"Why not use Indian Kanoon's API?"** Paid/limited and an outside network call with case facts; the project's rules are zero cost and fully local.

## F9. Engineering

101. **How do the embedder and the LLM share a 4 GB GPU?** They don't — they take turns: evict Ollama and confirm via `/api/ps`, load BGE-M3, encode and prefetch everything later stages need, free it, then generate.
102. **What did fp16 buy you?** ~5–6× faster indexing (84K chunks in ~21 min) and it fits the card.
103. **How is the live progress view done?** The pipeline emits start/done events with a summary of what each stage produced; the browser polls a job endpoint and draws them. Nothing is simulated.
104. **How many tests and what do they cover?** 413 pytest tests (counting parametrised cases) across ingestion, the pipeline nodes and rules, the API, retrieval, the graph and the evaluation code; fake embedders and scripted LLMs make the suite run in about 10 seconds without a GPU.
105. **How do you prevent a corrupted corpus?** The writer fsyncs and re-reads its own line count; the gate cross-checks every file against the build report; the build fails on mismatch.
106. **What's an example of a Windows-specific problem?** Hugging Face downloads failing with WinError 1314 (symlinks need admin) — fixed with `HF_HUB_DISABLE_SYMLINKS`; and Ollama models landing on C: because the service never saw the user-level variable.
107. **How long does indexing take?** ~25 minutes on the GPU at fp16.
108. **How do you handle a court order that is mostly procedure?** The intake step extracts alleged facts; if none are stated, it declines with `no_facts_stated` rather than charging procedural sections.
109. **What happens if Ollama is down?** The launchers start it; saved samples still work; a live run returns a clear 503.
110. **Where is the design record?** `CLAUDE.md` (rules, status, every gotcha) and `docs/` (one file per evaluation).

## F10. Process and reflection

111. **What did you learn most?** Read the data — automated checks confirm shape, not content. And move every decision that can be a rule out of the model.
112. **What went wrong in the project?** The hardening pass improved the dev set but a held-out set got worse (19 → 17 relevant verified); the graph-edge bug; repeated eval runs killed by memory; three weeks of gated-dataset waiting.
113. **What would you do differently?** Audit extracted edges on day one; write the external evaluation earlier; secure benchmark access first; pick a GPU with 8 GB if possible.
114. **How did you avoid overfitting?** Held-out sets written before changes, scored once and then "spent"; same-code ablations; the test split run once at the end.
115. **Why are there two frontends?** Streamlit was the planned one; the HTML page was added for a professional, offline, fully controlled design with a live pipeline view. Both call the same API.
116. **What's novel here?** Not the components — the combination: date-routed dual-code retrieval for the IPC→BNS transition, code-scoped graph verification with a retry loop, precedent bridging through a reviewed mapping, and an honest zero-shot evaluation on a 4 GB laptop.
117. **What's the biggest risk if deployed?** Over-trust: a user reading "verified" as "applies". Mitigated by the three-level display and the bare-act links; a real deployment would need lawyer review and user testing.
118. **Ethical concerns?** Privacy (solved by local-only); automation bias (labelled research aid); data licences (public judgments; NyayaAnumana and IL-TUR accessed under their terms; Hanno-Labs CC-BY-4.0).
119. **If you had one more month?** Lawyer review of the mapping and keys; a precision model over (facts, section) pairs; IL-TUR PCR for Node 3; more High Court data.
120. **Summarise the project in one line.** **A zero-cost, fully local legal research assistant that can't cite a section that doesn't exist — and is honest about how often it cites one that doesn't apply.**
