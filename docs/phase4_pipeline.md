# Phase 4: Single-Node Pipeline

*2026-09-27. Model `qwen3.5:4b` (Q4_K_M) via local Ollama 0.34.4, BGE-M3 query encoding on CPU, the real ChromaDB index and citation graph.*

## Gate result: PASS

To reproduce: `venv\Scripts\python.exe -u scripts\run_phase4.py --reps 3`. Raw output is in `docs/phase4_pipeline_raw.json`.

| Gate criterion (CLAUDE.md §8) | Result |
|---|---|
| 10 cases (5 pre-2024, 5 post-2024) route correctly **every time** | **30/30** runs (10 cases × 3 reps). The router returned the right era, retrieval touched only that era's collections, and every verified section is an ingested section of that era's code |
| A deliberately adversarial case triggers and survives the retry loop | **3/3** reps. BNS-era theft with retrieval withheld: round 0 `421` rejected → round 1 `378` rejected, with the hint "its BNS counterpart is BNS 303" → round 2 `303` verified |

Temperature 0 with a fixed seed made every rep identical, so "every time" here means reproducible, not averaged.

"Routes correctly" was checked three ways, because the router's own return value is the easy part:
1. `route(offence_date)` gives the case's era.
2. The runner wraps `store.retrieve` and records every collection queried. Nothing outside `ranker.ERA[era]` was touched. For the BNS that includes `judgments_pre2024`, whose IPC judgments vote only through the verified mapping. This is by design (Phase 2).
3. Every entry of `verified_sections` has `code == era` and passes `verify_section(g, era, s)`.

## What the pipeline is

```
route(offence_date)                      src/pipeline/router.py      plain function, no LLM
guardrail.check(facts, era)              src/pipeline/guardrail.py   insufficient -> return, no LLM call
ranker.rank_sections(..., device="cpu")  top-10 candidates + 300-char excerpts
embedder.free()
StateGraph (src/pipeline/graph.py):
  statute_identifier (Node 1, LLM) -> verifier (Node 2, graph lookup)
  verifier --(round left something unconfirmed AND retry_count < 2)--> statute_identifier
  verifier --(otherwise)--> END
```

The state has the eight §3 fields plus `era`, `retrieved` and `unconfirmed`. These were added at the plan stage; none of the eight is renamed. `candidate_sections` keeps every round's proposals (with `round`) so Phase 6 can compute the catch rate directly.

## Per-case results (identical in all 3 reps)

| # | era | offence | expected | verified | relevant? |
|---|---|---|---|---|---|
| 1 | IPC | theft | 378, 379 | 378, 411 | yes |
| 4 | IPC | breach of trust | 405, 406, 408 | 408, 420, 415 | yes |
| 5 | IPC | assault | 320, 322, 325, 326 | 326, 325, 324 | yes |
| 7 | IPC | cheating | 415, 420 | 420, 468, 471 | yes |
| 8 | IPC | common intention | 34, 322 | 323, 114, 307 | **no**: s34 not proposed |
| 9 | BNS | theft (worked example) | 303 | 303(1) | yes |
| 10 | BNS | snatching | 303, 304 | 309(2), 134 | **no**: robbery instead of snatching |
| 12 | BNS | assault | 116, 117, 118 | 116, 118(1) | yes |
| 13 | BNS | cheating | 318 | 318(4), 61(2), 316 | yes |
| 15 | BNS | common intention | 3(5) | 115(1), 309(6) | **no**: 3(5) not proposed |

Relevance is **7/10**. It is reported here, not gated; Phase 4's gate is routing plus the retry loop. Median wall time is 14 s per case: ~11 s LLM, ~2 s guardrail, ~0.5 s retrieval. One run of case 10 spent 251 s in CPU retrieval (every other run took ~0.5 s), so it was a one-off stall, not a pattern.

**Common intention is the weak spot in both codes.** Phase 2 predicted that s34 (retrieval rank 146) would have to come from Node 1. Node 1 does not supply it. For case 8 it proposes s114 ("abettor present"), which is the nearest thing it knows. The system prompt already allows "general provisions such as joint liability". Making it more specific would mean tuning on the gate case, so it was not changed. This carries into Phase 5/6 as an open quality issue. It is not a Phase 4 defect.

## Adversarial cases

| case | retrieval | round 0 | outcome | gated |
|---|---|---|---|---|
| BNS theft, no context | withheld | `421` | 421 ✗ → 378 ✗ (hint: BNS 303) → **303 ✓** | yes, 3/3 |
| BNS cheating, no context | withheld | `66, 67, 68` | all three **verified**: real BNS sections (sexual offences), wrong for these facts | no |
| BNS era, complaint says "Section 420" | normal | `318(1), 308(1), 351(1)` | bait not taken | no |
| BNS era, complaint says "Section 498A" | normal | `85, 308(1), 351(3)` | bait not taken; found cruelty (85) without a mapping hint | no |

What these show:

- **With retrieval context the model does not take IPC-number bait** (0/9 runs). A lawyer's "420" was answered with BNS 318 each time. This is why the bait cases could not be the gate case: they never exercise the loop.
- **Without context it invents**, and the loop works, but only after two prompt fixes made during this phase:
  1. The feedback was first a bare follow-up message. The model then re-proposed the same rejected `421` in all three rounds, the cap ended the loop, and nothing verified. Replaying its previous answer as an assistant turn and listing the rejected numbers as banned fixed it.
  2. Node 2's rejection now states the code's real span ("BNS 421 is not a section of the ingested BNS (sections 1 to 358)"). This is read off the graph, not typed from memory.
- **Graph verification checks existence, not applicability.** "BNS 66, 67, 68" for a college-admission fraud all verify, because they exist. This is the limit noted in `nodes.py`'s docstring, now demonstrated. Every verified entry carries the graph's own title, so a report shows "BNS 67: Sexual intercourse by husband upon his wife during separation" against a cheating case and the mismatch is visible. **Phase 5 must not treat `verified_sections` as "applicable sections"**: Node 4 grounds its counter-arguments on them.

## The insufficient-data guardrail

`scripts/calibrate_guardrail.py` (raw output in `docs/phase4_guardrail_raw.json`) measured two candidate signals over the 25 Phase 2 queries (dev + held-out) and 10 out-of-domain inputs. Each out-of-domain input was scored in both eras.

| group | best judgment cosine | best statute cosine |
|---|---|---|
| criminal facts (25) | **0.595**–0.740 | 0.486–0.603 |
| not legal (recipe, cricket, novel, gibberish) | 0.437–**0.557** | 0.323–0.518 |
| civil (tenancy, contract, partition) | 0.602–0.632 | 0.442–0.537 |
| tax / labour / family | 0.606–0.614 | 0.426–0.497 |

- **Best statute cosine separates nothing.** A tenancy dispute (0.537) outscores 10 of the 25 criminal cases. It was the planned signal and was dropped on this evidence.
- **Best judgment cosine separates criminal facts from non-legal text** with a gap of 0.557 to 0.595. The threshold sits at the midpoint, **0.576** (`MIN_JUDGMENT_SIMILARITY`).
- **No similarity threshold separates civil from criminal facts.** They score inside the criminal range on both signals. Forcing a line would refuse real cases. The fallback was a Node 1 instruction to return an empty list for purely civil disputes. **It did not work.** The tenancy probe came back as BNS 314 (dishonest misappropriation), 308(1) (extortion) and 351(1) (criminal intimidation), all verified. The pipeline currently does not decline civil matters. This is an open item for Phase 5/7, where the report has to say so, or a classifier step has to be added.

Probes: the recipe → `insufficient_data` in 2.6 s, no LLM call. The tenancy dispute → `ok` (expected `no_proposals`).

## Engineering notes

- **The output schema has to be bounded.** Unbounded, `qwen3.5:4b` listed sections until Ollama's 5-minute request limit killed it (~4,000 tokens at ~16 tok/s). `maxItems`/`maxLength` in the JSON schema end it by construction. `num_predict` is a backstop, and hitting it raises an error rather than returning truncated JSON.
- **`think: false`.** qwen3.5 is a thinking model and runs ~half on CPU here.
- **Query encoding is on CPU at runtime** (`device="cpu"`, threaded through `ranker`). Ollama keeps the model resident after a call, so a GPU-loaded embedder on the next query would share the 4GB card with it. The first CPU encode includes a ~9 s model load; later ones are sub-second.
- **Tests:** 56 new in `tests/pipeline/` (router boundary days, the citation parser, verifier invariants, and loop mechanics with a scripted LLM: cap at exactly 3 Node 1 calls, verified sections survive retries, an empty retry ends the loop, no LLM call on the guardrail path). 258 pass in all.

## Re-run after the data update (2026-09-27, later the same day)

The IPC↔BNS mapping was completed (97 → 574 rows reviewed, 538 with a BNS counterpart), 2026 Supreme Court judgments were ingested, and the index was rebuilt. Then `run_phase4.py --reps 3` was re-run unchanged. Raw output was overwritten in `docs/phase4_pipeline_raw.json`.

| | first run | re-run |
|---|---|---|
| routing | 30/30 | **30/30** |
| gated adversarial triggered + survived | 3/3 | **3/3** |
| relevant section verified (reported) | 21/30 | **24/30**; case 10 now hits (303 with robbery) |
| tenancy probe | charged as BNS 314/308/351 | **`no_proposals`**, as intended |
| bait cases triggered | 0/9 | 0/9 |

**The gated adversarial case changed path, and the change is instructive.** The first run went `421` ✗ → `378` ✗ (hint: BNS 303) → `303` ✓. The re-run goes `421` ✗ → `320` ✓. IPC 421 now has a verified BNS counterpart, BNS 320 (dishonest removal of property to prevent distribution among creditors). Node 2's hint says so, and the model takes it. The mapping is right and the hint is right. They faithfully translated the model's wrong first guess into that guess's real BNS equivalent, which verifies. The loop still fires, and no fabricated number is ever verified. The case now ends on a real section that doesn't apply, which is the existence-only limit again, reached through the hint. For Phase 5/6: a hint that translates a *wrong* guess is still a wrong guess, so the catch-rate metric should separate "caught" from "corrected to something relevant".

Case 8 (common intention) still misses: s34 is not proposed; it gets 149 (unlawful assembly, which needs five people, and the facts have four). Case 15 now retries once (`120B(1)` rejected) and still does not reach BNS 3(5).

## Broad-coverage baseline (held out, scored once)

`scripts/eval_broad.py` was run on `tests/fixtures/broad_coverage.json`: 20 cases written after Phase 4 covering homicide, dowry death, kidnapping, robbery, intimidation, forgery, negligent death, extortion, a lawyer-style brief and both boundary days. Raw output is in `docs/broad_coverage_raw.json`.

- **Routing 19/19; a relevant section verified in 19/19** (case 20 is an ungated limitation probe). On clear-cut offences, retrieval plus Node 1 finds the charge.
- **The weakness is over-charging, not missing charges.** Extra verified sections include IPC 302 on a dowry death, 120B (conspiracy) and 372 on a kidnapping, 307 on a single-blow sudden fight, 387 on a phone threat, and IPC 25, the *definition* of "fraudulently", on a forgery. Each is a real section, so each verifies. This is the same "verified ≠ applicable" problem, and it is now the main quality issue for Phase 5.
- **The boundary days route correctly.** 2024-06-30 → IPC 457/380; 2024-07-01 → BNS 331/303.
- **Case 20 (cruelty from January to September 2024)** routes to the BNS on the last incident's date and says nothing about the IPC-era acts. This is expected behaviour for a single-date router, and it is something the Phase 7 report has to warn about.
