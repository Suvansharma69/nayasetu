# Hardening pass: closing the Phase 1–4 open issues

*2026-09-27. Rule (owner): no Phase 5 until every earlier issue is resolved, with state of the art as the bar. Plan: `.claude/plans`, approved. This file is the evidence record, one section per register row.*

**Status legend:** ✅ closed with evidence · ⏳ closed pending a measurement listed below · 🔒 owner-only, cannot be closed by Claude

## Register

| # | Issue | Status | Evidence (details below) |
|---|---|---|---|
| 1 | Over-charging: verified ≠ applicable | partly | held-out 2: precision 44% (57% with the advisory doubts set aside); extras about 1 per case; not halved
| 2 | Definitional sections proposed and voted (BNS 2, IPC 25) | ✅ | `chargeability.json` from the codes' chapters; Node 2 rejects non-chargeable proposals; excluded from candidates and votes |
| 3 | Common intention never proposed | ✅ (dev) / ⏳ (frozen) | liability rule from Node 1's fact profile: dev case 8 → IPC 34, case 15 → BNS 3(5), both now charged |
| 4 | Retry hint faithfully translated a wrong guess | ✅ | hint now names both titles plus a caveat; Node 2b judges the result |
| 5 | Civil disputes and false declines | ⏳ | model decline removed (`0203e85`, #14 re-run: BNS 351 charged); held-out 3 found a SECOND path, the guardrail (#7), now fixed (`6f09d4f`: never a bare refusal). Certify on held-out 4 |
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

## Frozen results (2026-09-29)

**Phase 4 gate, full re-run (resumable runner): PASS.** Routing 30/30 (identical across reps); relevant section verified **30/30** (Phase 4 original 21/30, after the data update 24/30); gated adversarial triggered + survived 3/3; recipe → `insufficient_data`, tenancy → `no_offence_disclosed`. Slowest run 103 s, no stalls.

**Broad-coverage held-out set, scored once: a SETBACK, recorded as is.**

| 19 gated cases | before hardening (Phase 4 pipeline) | after hardening |
|---|---|---|
| routed | 19/19 | 19/19 |
| relevant section verified | **19/19** | **17/19** |
| relevant section among charges | – | 16/19 |
| extra sections | 19 | 15 (−21%) |

Done-criteria: routing met; **recall ≥ 18/19 NOT met; extras halved NOT met. The dev-set gains did not generalise.**
- Case 2 (single-blow sudden fight): Node 1 now proposes murder (IPC 300/302) instead of culpable homicide (299/304). New, and legally wrong.
- Case 18 (house-breaking by night): Node 1 proposes 379 instead of 380/457.
- Case 4 (kidnapping a 15-year-old): 361 and 366 verified, but the two-pass applicability check rejected both.
Cases 2 and 18 point at Node 1's prompt change (the fact-profile fields added for the decline and liability rules) shifting the 4B model's proposals. Case 4 is the applicability judge's known weakness. The run was also memory-starved (a slow retrieval logged with 0.4 GB free).

Per the anti-overfitting protocol, this set is now spent for the current method: **nothing may be changed because of these results without writing a new held-out set.** Any diagnosis must happen on the dev set.

## Dev-set ablation and the frozen method (2026-09-30)

After the broad-coverage setback, each hardening change was switched off in turn on the **dev set only** (`PRAMANA_ABLATE`, `src/pipeline/ablation.py`; results in `docs/abl_*_runs.jsonl`):

| dev set, 15 cases | relevant verified | relevant among charges | extras verified / charges |
|---|---|---|---|
| full | 14 | 10 | 30 / 19 |
| judge off | 14 | **14** | 29 / 29 |
| profile off | **12** | 10 | **37** / 21 |

Decisions:
- **Node 2b becomes advisory** (`graph.JUDGE_GATES = False`). As a gate it removed the right charge in 4 of 15 cases for a precision gain of 38% → 42%. Every verified section is now a charge, and the judge's doubts travel beside it as `doubted`, with the missing ingredient it named, for the report to show.
- **The fact-profile questions stay.** With them off, recall falls (14 → 12: common intention is lost again) and extras rise (30 → 37).
- The chargeability rule stays regardless: a definition is never a charge.
- `no_exclude`, `no_chargeability` and the all-off baseline did not finish (the runs kept being killed for low memory; 6/15 of `no_exclude` done). They do not change the decisions above and are queued in `scripts/run_final_evals.bat` for the record.

**Method frozen 2026-09-30.** The next step is `tests/fixtures/heldout_2.json` (written and committed before any ablation result existed), scored once. It must run from a normal terminal: `scripts\run_final_evals.bat`. Jobs started from inside Claude Code, even as a "detached" process, are killed under memory pressure on this laptop.

## Held-out set 2: the frozen method, scored once (2026-10-01)

Run from a normal terminal (`scripts\run_final_evals.bat`); raw: `docs/heldout_2_hardened_runs.jsonl`.

| 16 cases, never seen while building | result |
|---|---|
| routed correctly | **16/16** |
| right section charged | **14/16 (87.5%)**, in line with broad-coverage (17/19 = 89%) |
| charge precision | 17/39 = 44% |
| extra sections the advisory judge flagged as doubtful | **10 of 17**, and it doubted **0** correct sections |
| precision if doubted sections were set aside in the report | 17/30 = 57%, recall unchanged (14/16) |
| supporting quotes found verbatim in the facts | 69/69 |

The advisory judge did well here (it flagged three of the four bogus murder sections on an attempted murder, and both unlawful-assembly sections on a three-person case), while on the dev set it had rejected correct charges. That is exactly why it informs and does not decide. No method change is made on the strength of this one-shot result.

**Misses:**
- #3 (petrol-pump cashier keeps the cash): IPC 409 (breach of trust by a public servant or banker) instead of 408 (by a clerk or servant).
- **#14, a false "no offence disclosed": open, SAFETY.** A man shouting that he will burn a family's house down with them inside was declined as "a civil dispute". The 2026-09-27 fix (decline only on "no offence" AND no sections) cannot catch this, because the model said both. **A false decline is the most harmful output this system can produce.** Proposed design, to be built and tested on the dev set, then checked on a NEW held-out set: never return a bare decline. Either (a) decline only when two independent prompts agree, or (b) on a decline, still show the top retrieved candidate sections under "the system found no offence; review these".

**Dev ablation, complete** (verified level, 15 cases): all changes off (the Phase 4 pipeline on corrected data) recall 12/15, precision 33%; all on 14/15, 38%; profile off 12/15, 30%; exclusion off 14/15, 39%; chargeability off 14/15, 39%. The hardening helped modestly. The exclusion and chargeability switches move results by less than one case.

## Pending measurements (to be filled by the frozen runs)

- Phase 2 retrieval re-score (dev + held-out, once).
- ~~Out-of-domain probes~~ done: 10/10.
- ~~Phase 4 gate~~ done: PASS.
- ~~Broad-coverage, frozen~~ done: setback (above).
- IL-TUR LSI dev sample and frozen test sample: **blocked on access** (row 13).

## 2026-10-03: held-out 3, the guardrail false decline, and three changes

**Held-out 3** (`tests/fixtures/heldout_3.json`, criminal facts inside civil-looking disputes; frozen `41fd7c5`, scored once): routed 10/10, **recall 6/10** (`score_runs.py`, definition == punishment), precision 31% (60% with the judge's doubts set aside: it doubted 13 of 23 extras and **no** correct charge), civil controls 2/2 with a warning and a review list. **One false decline, by the guardrail** (#7, mischief, judgment similarity 0.555 < 0.576). Misses #2, #9, #10 are retrieval: the right section ranked 4th, 17th and 17th, and Node 1 charges what it is shown.

**Changes (`6f09d4f`), each with an ablation switch:**
1. Guardrail: no LLM on weak context, but never a bare refusal - the nearest statute sections are returned for review.
2. `punish`: a verified IPC definition becomes its punishing section (405 -> 406), the judge reading both texts.
3. `dual`: Node 1 sees fused top 10 + statute-text top 10. Dev top-10 coverage: fused 13/15, statute 14/15.

Also: runtime query encoding moved to the GPU after evicting Ollama (`41fd7c5`), 36 s -> 18 s per case, same output.

**Pending:** dev comparison (`scriptsun_dev_compare.bat`, baseline 9/15 done when a memory kill stopped it), then held-out 4 (`tests/fixtures/heldout_4.json`, committed `de982c0` before any dev result), scored once.
