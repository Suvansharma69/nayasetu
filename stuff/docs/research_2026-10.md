# Research notes: improving statute identification (2026-10-01)

*Prompted by the hardening pass's held-out results: right section charged 87.5–89%, about one extra section per case, one false "no offence". The owner asked for the best known methods from the literature and existing tools.*

## What the literature says

**1. The retriever, not the LLM, is usually the bottleneck.**
- [ILSIC (EACL Findings 2026)](https://arxiv.org/abs/2602.00881), Indian statute identification from 8K layperson queries over 567 statutes: RAG with an SBERT retriever *underperformed* two-shot prompting, because the retriever put the right statute in its top 15 only ~32% of the time.
- Same paper, calibration for us: **GPT-4.1 reaches ~32% micro-F1** zero-shot (14.4% macro-F1). Llama-3-8B and Gemma-3-12B reach 18–30% micro-F1, and fine-tuning raises Gemma-3 to 33.2%.
- Its failure taxonomy matches ours exactly: *hallucinated* statutes, *non-applicable* statutes, and *technically misaligned* statutes (related but wrongly scoped, like our IPC 409 for 408).

**2. Multi-stage retrieval with reranking is the standard winning pattern.**
- [COLIEE 2025 overview](https://dl.acm.org/doi/10.1145/3769126.3785016): every team in the case-retrieval task used multi-stage pipelines. The best statute-retrieval system (Task 3) retrieved a small candidate set, reranked it with an LLM-based cross-encoder, then decided with multiple LLMs. Another system: BGE-M3 pre-ranking, then a fine-tuned BGE-M3 or LLM2Vec reranker, then majority voting.
- [Hybrid approaches for COLIEE 2025](https://link.springer.com/article/10.1007/s12626-026-00208-x): BM25 + dense candidates, query reformulation, ensembling, reranking.
- `BAAI/bge-reranker-v2-m3` (568M cross-encoder) is the reranker trained alongside our BGE-M3 embedder and is used in legal search pipelines ([e.g.](https://arxiv.org/pdf/2508.00679)).

**3. Hybrid scoring beats dense-only.** [BGE-M3](https://huggingface.co/BAAI/bge-m3) produces dense, sparse (lexical) and multi-vector scores from one forward pass. On MIRACL, dense-only scores 67.8 nDCG@10 and all three combined 70.0. Our index uses dense only.

**4. Structure-aware recall expansion helps recall but needs reranking.** [NyayGraph (NLLP 2025)](https://aclanthology.org/2025.nllp-1.11.pdf) built an IPC knowledge graph (chapters, cross-references, NCRB crime heads) and expanded retrieved sections through it on IL-TUR LSI: "explicit KG inference significantly enhances recall", but feeding the KG into the LLM prompt "enhances coverage at the expense of precision, underscoring the importance of good reranking". A later study reports its test recall@10 as 0.090, so it is a weak baseline.

**5. Listwise LLM reranking** (RankGPT and its open distillations RankZephyr/RankVicuna, the [RankLLM](https://castorini.github.io/rank_llm/) toolkit) is state of the art on general reranking. It needs 7B+ models to be reliable; our 4B model's measured instability makes it a poor fit here.

## What Pramana adopts, and why

| # | Change | Evidence | Cost | Status |
|---|---|---|---|---|
| 1 | **The model can never decline a case**; prima facie (FIR/charge-stage) framing in Node 1 | owner: missing an offence is the primary error; two measured false declines | none | done (`0203e85`) |
| 2 | **Node 1 two-ordering union** (original and reversed candidate order) | COLIEE's best system decided with multiple LLMs; our measured order-sensitivity | +1 LLM call | **tried and switched off** (`nodes.NODE1_UNION = False`): see "Node 1 union" below |
| 3 | **Cross-encoder reranking** of the top 40 statute candidates (bge-reranker-v2-m3) | ILSIC: retriever bottleneck; COLIEE: multi-stage pattern | 2.27 GB download; ~11 s/case on CPU | **tried and rejected**: see "Cross-encoder reranker" below. Code removed (in git history at `02c756e`). |
| 4 | BGE-M3 sparse/hybrid statute scoring | MIRACL 67.8 → 70.0 | no download | **tried and rejected**: on the dev set, sparse alone scored top-3 2/15 and top-10 5/15; fused with the current ranking it scored 7/15 and 11/15 against 11/15 and 13/15 without it. Facts are narrative and statutes abstract, so lexical overlap is the wrong signal (the MIRACL gain comes from queries that share vocabulary with their passages). Code removed. |
| — | Fine-tuning | out of scope: CLAUDE.md §2 forbids it (RAG, not fine-tuning) | | not adopted |
| — | Listwise LLM reranking with qwen3.5:4b | 4B judgments measured unstable (dev ablation) | | not adopted |

Every change is evaluated on the dev set (ablation switches in `src/pipeline/ablation.py`) and then on a **new** held-out set. `heldout_2.json` is spent for the method it scored.

## Measured on the dev set (2026-10-01)

- Current ranking (pipeline mode): **top-3 11/15, top-10 13/15**. So for 13 of 15 cases the right section is already in Node 1's ten candidates. That is the room a reranker (item 3) has to work with: lifting top-3 towards 13.
- Hybrid sparse: rejected (see the table).

## Node 1 union, measured on the dev set (2026-10-01)

Both runs on the same code (`e193a90` plus the switch), only `union` differing; raw: `stuff/docs/single_dev_runs.jsonl`, `stuff/docs/union_dev_runs.jsonl`.

| 15 dev cases | single call | union of two orderings |
|---|---|---|
| a relevant section charged | 14/15 | 14/15 |
| relevant sections charged | 20/31 | 22/31 |
| sections per case | 3.8 | 5.6 |
| precision | 20/57 = 35% | 22/84 = 26% |
| Node 1 time | 1 call | 2 calls (~+40 s/case on this laptop) |

The two gains were IPC 405 in case 4 (the *definition* of criminal breach of trust; the charge is 406) and BNS 303 in case 11, where the aggravated theft (305) was already charged. Neither is a missed offence, which was the reason for adopting the union. **Switched off.** `NODE1_UNION = True` restores it.

**Bug found by this run, fixed (`e193a90`):** the joint-liability rule compared section numbers only, so the model proposing a bare BNS `3` (general explanations, rejected by Node 2 as non-chargeable) suppressed the rule's BNS 3(5). Dev case 15 lost common intention that way. The baseline comparison above includes the fix; case 15 charges BNS 3(5) in both runs.

Note on the earlier comparison: the first union run was compared with `abl_full` (2026-09-29), which predates the recall-first prompt (`0203e85`). That comparison mixed two changes; the table above does not.

## Cross-encoder reranker, measured on the dev set (2026-10-01)

`bge-reranker-v2-m3` (weights sha256-verified against the hub), rescoring the top 40 of the pipeline's ranking (non-chargeable sections excluded, as Node 1 sees it). Raw: `stuff/docs/rerank_phase2_testset_raw.json`, `stuff/docs/rerank_dev.log`.

| 15 dev cases | recall@1 | recall@3 | recall@5 | recall@10 |
|---|---|---|---|---|
| current ranking | 4 | **11** | 11 | 13 |
| reranker alone | 3 | 5 | 9 | 13 |
| RRF of the two (k=60) | 4 | 8 | 11 | 14 |

**Rejected.** The reranker halves top-3 recall. It fails the way BGE-M3 sparse did: it rewards surface overlap between narrative facts and the statute text. A theft from a house ranks the house-breaking sections (IPC 442, 448, 453) above theft. A two-man phone snatching ranks BNS 78 (stalking) first, and a cheating case ranks BNS 344 first. RRF buys one case at recall@10 for three lost at recall@3. The current ranking's precedent votes, which come from what courts actually charged on similar facts, carry the signal this general-domain cross-encoder lacks. A reranker fine-tuned on Indian charge data could change this, but CLAUDE.md section 2 rules out fine-tuning.

The weights are still in `D:\hf-cache\local\bge-reranker-v2-m3` (2.2 GB) and can be deleted whenever needed. Nothing loads them.
