# Hardening pass: closing the Phase 1–4 open issues

*2026-09-27. Rule (owner): no Phase 5 until every earlier issue is resolved, with state of the art as the bar. Plan: `.claude/plans`, approved. This file is the evidence record, one section per register row.*

**Status legend:** ✅ closed with evidence · ⏳ closed pending a measurement listed below · 🔒 owner-only, cannot be closed by Claude

## Register

| # | Issue | Status | Evidence (details below) |
|---|---|---|---|
| 1 | Over-charging: verified ≠ applicable | ⏳ | dev: extra sections 28 → 12 with **no** relevant section lost; frozen broad-coverage pending |
| 2 | Definitional sections proposed and voted (BNS 2, IPC 25) | ✅ | `chargeability.json` from the codes' chapters; Node 2 rejects non-chargeable proposals; excluded from candidates and votes |
| 3 | Common intention never proposed | ✅ (dev) / ⏳ (frozen) | liability rule from Node 1's fact profile: dev case 8 → IPC 34, case 15 → BNS 3(5), both now charged |
| 4 | Retry hint faithfully translated a wrong guess | ✅ | hint now names both titles plus a caveat; Node 2b judges the result |
| 5 | Civil disputes not declined | ✅ | probes 10/10 declined; decline needs "no offence" AND no sections |
| 6 | Offence period straddling 1 Jul 2024 | ✅ | `route_period` + dual-code run with a warning; tests at the boundary |
| 7 | Phase 2 held-out 10 → 8/10 after the mapping change | ⏳ | re-score pending (retrieval changed again: graph edges and exclusions) |
| 8 | **Citation-graph edges: 63% precision (found in this pass)** | ✅ | fresh 100-edge audit: **96%** after the fix |
| 9 | Bombay HC lost-ligature words | ✅ | 140 reviewed repairs, 1,294 occurrences in 137 judgments |
| 10 | spotcheck "4.6% tails cut off" unexplained | ✅ | explained; true mid-sentence splits 1,190 → **122 (0.1%)** |
| 11 | Devanagari U+FFFD | ✅ unfixable | all 7 inside Devanagari quotations (≥37 Devanagari chars nearby each); lossy PDF font |
| 12 | Retrieval stalls | ✅ explained (memory pressure) | not reproduced in ~100 runs since; `retrieve()` now logs encode/query split and free RAM for any call over 20 s |
| 13 | IL-TUR access | 🔒 | request pending manual approval by Exploration-Lab (HTTP 403 on data files). Harness built and tested: `scripts/eval_lsi.py` |
| 14 | Legal labels reviewed by Claude, not a lawyer | 🔒 | stays open until a lawyer reviews them |

## 8. The citation-graph precision defect (the largest finding)

Auditing 100 random case→section edges against the citation the extractor itself matched showed **37 were not penal-code sections** (~63% precision). The graph feeds Node 3's precedents and the retrieval votes, so more than a third of its edges pointed at the wrong law. Causes and fixes (`src/ingest/sections.py`):

| cause | example | fix |
|---|---|---|
| enactment named **before** the section (SCR headnotes) | `Evidence Act, 1872 – ss.4, 112` | look-behind `_preceding_enactment` |
| bare procedure sections | "petition under Section 482", "Section 167" | corpus-derived trust: a number named as another Act's more often than as penal is not trusted when bare (`scripts/build_citation_trust.py`; 482: 2 penal vs 3,044 other) |
| enactment forms not recognised | `138 N.I.Act`, `", and 29 of the Narcotic…"`, `"of the 2017 Act"` | acronym/year Act patterns; `, and` and `read with section` join a compound |
| sub-section of another section | `sub-Section 5 of Section 21 of the NIA Act` | `_OF_SECTION` |
| not a citation | `S.2587/2011` (a suit number) → IPC 258 | digit boundary in `_NUM` |

Result: edges 24,475 → 16,514. Real offences held steady (IPC 420: 885, 302: 688, 34: 821, 379: 158); phantoms collapsed (IPC 482 ~1,900 → 18). **A fresh random sample of 100 edges (new seed, not the one that shaped the fix): 96 correct.** The remaining 4 motivated the last two rules; each audited string is now a test. 47 NyayaAnumana judgments stopped qualifying for the subset, because their only "offence" citations were bare procedure numbers. One newly qualified.

## 1–4. Pipeline changes (dev set only for every decision)

- **B. Chargeability** (`scripts/build_chargeability.py`, `src/pipeline/chargeability.py`): offence / liability / non-chargeable, from the chapter each section sits in. IPC: 446 offence, 20 liability, 109 non-chargeable. BNS: 295 / 19 / 44, plus BNS 3(5) as the only liability sub-section of BNS 3.
- **C. Node 2b applicability** (`src/pipeline/applicability.py`): the section's ingested text plus the facts. The model must quote the facts; a quote counts only if it is an exact substring of them. Supported = model says it applies + at least one grounded quote + no missing ingredient named. Nothing is deleted: the report separates `charges` from `unsupported`. Three prompt variants were measured on the dev set: quotes-first 14/16 relevant kept, 13/28 extras removed (chosen); missing-first with an "over-includes" framing 9/16, 24/28; missing-first neutral 11/16, 17/28. **The honest finding: qwen3.5:4b is a mediocre applicability judge.** Asked for the missing ingredient first, it becomes hyper-literal and legally wrong (it says a fracture is "not shown" to be grievous hurt, though IPC 320 defines it as such). Recall won, because losing the right charge is the worse error.
- **Headcount rules** (in C): an unlawful assembly needs 5+ persons (IPC 141–149, BNS 189–191); joint liability and conspiracy need 2+. Decided by rule from Node 1's `accused_count`, never by the model.
- **D. Liability rule**: 2+ accused acting together with a shared plan → IPC 34 / BNS 3(5); 5+ with a common object → IPC 149 / BNS 190. Verified and judged like any proposal.
- **Per-section vs batched**: per-section calls kept 15/16 but removed only 6/28 extras. In isolation a small model says yes to almost anything, so the check stays batched.

Dev set end to end (`docs/hardening_dev_v2_raw.json`): routed 15/15; a relevant section among the charges 14/15 (the applicability check dropped **0** relevant sections); extras 28 → 12; supporting quotes grounded 85/85.

## 9–11. Phase 1 data

- **Bombay ligatures:** candidates were derived from the corpus's own vocabulary. A token absent elsewhere qualifies when one inserted letter after an `f` gives a common word, with no second candidate. All 140 pairs were read, none rejected, and they are stored with provenance in `data/mappings/bombay_ligature_repairs.json`. This replaces the earlier dictionary guess, which produced false repairs.
- **Mid-sentence splits:** 965 of 1,190 were SCR headnotes (clauses joined by ` – ` and `;` with no full stop) cut at an arbitrary space by the long-sentence fallback. `textsplit._hard_split` now cuts at the strongest clause boundary. spotcheck now counts only true continuations (the next chunk opens in lowercase): 0.1%.

## Later findings (same day, after the data rebuild)

- **The decline rule once produced a false "no offence"**: dev case 10 (a two-man phone snatching). The model answered `discloses_offence: false` while its own `why` described a theft and it proposed BNS 303. The rule now declines only on "no offence" **and** no sections; a contradiction proceeds, with a warning. Re-run: status ok, BNS 303 charged.
- **Instability of the applicability judge**: on the rebuilt data, dev case 13 lost BNS 318 (the right charge) to Node 2b, which did not happen in the previous run. The prompt's candidate list changed, and the 4B model's judgment moved with it. Open: to be measured over the full dev set once the evaluation chain can run again.
- **HyDE (statute search with an LLM restatement of the facts) was tried and rejected on the dev set**: 11/15, the same as without it. It fixed both common-intention cases but lost three theft cases, whose restatements drifted towards "receiving stolen property" and "cheating". An extra LLM call for no net gain. The code stays, off (`ranker.rank_sections(statute_query=...)`, `src/pipeline/hyde.py`), with this measurement recorded.
- **Phase 2 retrieval on the corrected data**: frozen method dev 11/15, held-out 7/10 (18/25 = 72%, below the 80% bar). Pipeline mode (non-chargeable excluded) dev 11/15. Both flips are rank-3/4 swaps in the vote channel after the phantom graph edges were removed. The corrected graph is not reverted to win back a proxy metric. **Row 7 stays open**: the external measure (IL-TUR) is what decides it.
- **The evaluation chain was stopped by Claude Code for low system memory** after 13 of 15 dev cases; probes, Phase 4 gate and broad-coverage did not run. Not restarted without the owner's go-ahead.

## Results after resuming (2026-09-27, evening)

- **Dev set, full pipeline (`hardening_dev_v4`)**: routing 15/15; a relevant section verified 14/15; among charges only 10/15. The single-pass applicability check wrongly rejected 4 relevant sections, with legally wrong reasons ("theft requires moving out of the house"; the facts "do not explicitly state" dishonesty). The previous run had lost 0. **Remedy: two-pass self-consistency.** The check runs twice with the section order reversed, and a section is demoted only if both passes reject it. On the same verified sets: one pass kept 13/18 relevant and removed 19/31 extras; two passes kept 15/18 and removed 16/31 (section-level F1 0.60 → 0.63; no check at all: 0.54). Adopted. **Residual: 3/18 correct charges still land in the "verified, not shown to apply" tier.** They stay visible there with the model's reason. That is the ceiling of a 4B judge.
- **Out-of-domain probes: 10/10 declined correctly** (6 civil/tax/labour/family → `no_offence_disclosed` with a reason; 4 non-legal → `insufficient_data` before any LLM call). **Row 5 closed.**
- **Phase 4 gate re-run: stopped by Claude Code for low memory after 23 of 42 runs.** In those 23: routing 23/23, identical across reps; a relevant section verified in every gate case, including both common-intention cases and the snatching case; the gated adversarial case triggered and survived; the second no-context case now also triggers and self-corrects to BNS 318.
- **Row 12 (the stall) explained**: in the stopped run, one case took 1,819 s. The new instrumentation logged **no** slow retrieval, so the time went in the LLM stage while system memory was critically low (the job was reaped minutes later). Both stalls seen so far were memory pressure paging Ollama out, not a code defect. Mitigation is operational: run long evaluations with memory-heavy apps closed, or from a terminal outside Claude Code's background reaper.

## Pending measurements (to be filled by the frozen runs)

- Phase 2 retrieval re-score (dev + held-out, once).
- Out-of-domain probes (`scripts/eval_probes.py`).
- Phase 4 gate (`scripts/run_phase4.py --reps 3`).
- Broad-coverage, frozen (`scripts/eval_broad.py`).
- IL-TUR LSI dev sample and frozen test sample: **blocked on access** (row 13).
