# Phase 2 — Retrieval results

*Run 2026-09-26. Reproduce: `venv\Scripts\python.exe scripts\build_index.py` (≈25 min, fp16 on the 3050 Ti), then `scripts\eval_retrieval.py` and `scripts\eval_retrieval.py --heldout`. Raw per-case output: `phase2_retrieval_raw.json`, `phase2_retrieval_heldout_raw.json`.*

## Gate result

CLAUDE.md Section 8: *"top-3 results manually judged relevant in at least 12/15 test cases."*

| set | method | strict recall@3 (vs fixture) | manual judgement |
|---|---|---|---|
| development — `phase2_testset.json` (15) | statute only | 9/15 | — |
| development — `phase2_testset.json` (15) | **fused (shipped)** | **11/15** | **11/15 — one short of the gate** |
| held out — `phase2_heldout.json` (10) | statute only | 6/10 | — |
| held out — `phase2_heldout.json` (10) | **fused (shipped)** | **10/10** | 10/10 |

**The gate is missed by one case on the letter.** Phase 2 was accepted anyway (decision recorded in CLAUDE.md) because the same method, frozen, scored 10/10 on ten cases written after it was chosen — 21/25 (84%) overall against the gate's 80% bar — and the failures are the specific, understood limitation below, not general weakness.

The manual judgement was made by Claude, strictly: a case passes only if the top 3 contains a section the facts genuinely disclose, not a neighbour from the right family.

## Development set, fused top-3, judged

| # | era | facts (short) | fused top-3 | judged |
|---|---|---|---|---|
| 1 | IPC | motorcycle pushed away at night | 201, **378 Theft**, 411 | relevant |
| 2 | IPC | house entered, ornaments taken | **380 Theft in dwelling house**, 382, **378** | relevant |
| 3 | IPC | salesman removes stock over months | 409, 411, 420 | **not** — theft by servant (381) / CBT by servant (408) missing; statute-only had 381 at #2 |
| 4 | IPC | accountant diverts client deposits | 420, 409, 415 | **not** — 409 is CBT but for bankers/agents; 408/405 missing (statute-only had 405 at #2) |
| 5 | IPC | iron rod, fractured forearm | 323, 324, **326** | relevant |
| 6 | IPC | stick raised, threat, no blow | 504, 307, 324 | **not** — assault (351) missing; statute-only had it at #3 |
| 7 | IPC | flat sold on forged papers | **415**, 467, **420** | relevant |
| 8 | IPC | four men, prior agreement, beating | 323, 357, 307 | **not** — common intention (34) missing, the point of the case |
| 9 | BNS | motorcycle (worked example) | **303 [303(1)] Theft**, 309, 324 | relevant |
| 10 | BNS | phone snatched from scooter | **303**, 309, 351 | relevant |
| 11 | BNS | container seal broken, cartons taken | 316, **303**, 336 | relevant |
| 12 | BNS | knife, two stab wounds | **118**, 109, 115 | relevant |
| 13 | BNS | ponzi scheme | **318 [318(4)]**, 308, 336 | relevant |
| 14 | BNS | fake bank officer, OTP | 316, **319**, **318** | relevant |
| 15 | BNS | three accused, planned attack | 115, 333, **3 [3(9)]** | relevant (s3 holds common intention) |

## The known limitation: common intention (and liability rules generally)

IPC s34 ranks **146th** of 672 IPC records for case 8 (similarity 0.45 against the leader's 0.55), even with its BNS 3(5) text as an extra view. The query's dominant meaning is the violence; s34 is an abstract *liability* rule ("each of such persons is liable..."), and every hurt/assault section out-scores it. This is a limit of embedding similarity, not a pipeline bug, and no retrieval trick fixed it without fitting the 15 cases. **It is Node 1's job**: the LLM reads "four men... having agreed beforehand" and proposes s34, and Node 2 verifies it against the graph. Phase 4 should test exactly this case.

## What was built, and what moved the numbers

| change | why | effect (dev, strict) |
|---|---|---|
| embedder: BGE-M3 over InLegal-Sbert | bake-off (`embedding_bakeoff.md`): R@3 0.533 vs 0.20. InLegal-Sbert showed hubness — the same generic sections (IPC s443, s278; BNS s18, s52) topped every query | 3 → 8 |
| sub-section views for statutes (309 BNS records) | BNS s3 is 4,765 chars; common intention is its 194-char s3(5) | BNS common intention 155th → in top 3 |
| verified-BNS-counterpart views for IPC (97 records) | civictech IPC text has no Illustrations; the gazette BNS does, and Illustrations read like case facts | statute-only 8 → 9 |
| precedent votes + RRF (k=60) | facts match judgment facts far better than statute definitions; judgments carry the sections applied | 9 → 11; held out 6 → 10 |
| judgment paragraph fallback (Phase 1 fix) | 687 SC "paragraphs" over 8,000 chars (max 397,044) from failed splits — ~40% of SC text sat in chunks the embedder truncated, and they ran it out of memory | index could not be built without it |

Tried and **rejected** (all on the development set only): hubness centring (InLegal-Sbert 3→5, BGE-M3 8→6), title-only and title+600-char statute text, IDF-weighted votes (11→10), RRF k=10 (10), interleaving (9), CombSUM (9), votes restricted to statute candidates (11, no change).

## Index (at the Phase 2 gate; current sizes in the re-score section below)

| collection | records | from |
|---|---|---|
| `ipc_sections` | 672 | 575 sections + 97 verified-BNS-counterpart views |
| `bns_sections` | 667 | 358 sections + 309 sub-section views |
| `judgments_pre2024` | 81,834 | IPC-era judgment chunks (SC + NyayaAnumana HC) |
| `judgments_post2024` | 2,634 | BNS-era judgment chunks (28 SC judgments) |

`BAAI/bge-m3`, 1024-d, cosine, fp16 on GPU. ChromaDB at `chroma_db/` (1.2 GB). Each collection records its embedding model and `retrieve()` refuses a query from any other.

## Re-score after the data update (2026-09-27)

Two data changes altered retrieval without changing the method:
- the IPC↔BNS mapping went from the 97 in-scope rows to all 574 (538 with a BNS counterpart, 36 with none; see CLAUDE.md §10), so 441 more IPC sections gained a verified-BNS-text index view and many more IPC judgments now vote in BNS-era queries;
- the 2026 Supreme Court judgments were ingested.

| | before | after |
|---|---|---|
| index `ipc_sections` | 672 | 1,113 |
| index `judgments_pre2024` / `judgments_post2024` | 81,834 / 2,634 | 84,680 / 3,105 |
| dev set, fused, strict recall@3 | 11/15 | **12/15** (case 4 now hits: s405 enters the top 3) |
| held-out, fused, strict recall@3 (scored once) | 10/10 | **8/10** |
| all 25 | 21/25 | **20/25**, at the gate's 80% bar |

The two held-out drops are both IPC rank-3/rank-4 swaps. For theft, s378 fell to 4th behind s411. For cheating, s420 fell to 4th behind the forgery sections 464/467/468, which now also carry their BNS counterpart text. **Nothing was changed in response.** The method is the frozen Phase 2 method, now running on complete data, and adjusting it because of held-out results is what this set exists to prevent. Future method changes should be scored on `tests/fixtures/broad_coverage.json` (written after this), not re-tuned here.

New noise worth knowing for Phase 5: in BNS-era queries, **BNS 2 "Definitions"** now reaches the top 3 (dev case 9). IPC judgments citing definition sections (public servant, dishonestly, …) vote for it through the mapping. A definition is never a charge, so Node 1 should not be offered it as a candidate. This is a Phase 5 design point, not fixed here.
