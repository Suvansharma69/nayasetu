# Documentation

## Start here

| File | What it is |
|---|---|
| [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md) · [`.pdf`](PROJECT_GUIDE.pdf) | the complete guide: design, data, results, problems met, question bank |
| [`paper/`](paper/) | research paper: `pramana.tex` (IEEE, compile on Overleaf), `pramana.html`, `pramana.pdf` |
| [`synopsis/`](synopsis/) | project synopsis for the university, Word and PDF |
| [`evaluation_results.md`](evaluation_results.md) | every evaluation in one place, with the command that reproduces it |

## Design and evaluation reports

| File | Topic |
|---|---|
| [`embedding_bakeoff.md`](embedding_bakeoff.md) | why BGE-M3 and not InLegal-Sbert (measured on 15 cases) |
| [`phase2_retrieval.md`](phase2_retrieval.md) | retrieval method and the Phase 2 gate, case by case |
| [`phase4_pipeline.md`](phase4_pipeline.md) | router, guardrail, Nodes 1–2 and the retry loop; the Phase 4 gate |
| [`hardening.md`](hardening.md) | the hardening pass: citation-graph audit, legal rules, open-issue register |
| [`research_2026-10.md`](research_2026-10.md) | methods tried and rejected (reranker, Node 1 union, …) |
| [`accuracy_2026-10-07.md`](accuracy_2026-10-07.md) | the accuracy pass: completed IPC text, "no facts stated" orders |

## Run records

Every number in the reports above comes from a saved run, committed here so it can be checked. The file names follow one pattern:

| Pattern | Contents |
|---|---|
| `<run>_runs.jsonl` | one line per case: routing, verified sections, charges, doubted and extra sections, the fact profile |
| `<run>_raw.json` | the run as a whole: model, fixture, totals and per-case scores |
| `<run>.log` | console output of the run |
| `iltur_lsi_{dev,test}_100*` | the IL-TUR benchmark runs (`_summary.json` holds the headline scores) |

Main runs: `phase4_*` (Phase 4 gate), `phase6_*` (external court orders), `heldout_*` (held-out sets, each scored once), `abl_*` (ablations, one component switched off), `rules_dev*` / `pair_dev*` / `dual_dev*` (development-set comparisons), `iltur_lsi_*` (benchmark). The web interface's System view and `GET /stats` read some of these files directly, so they are kept at these paths.

## Images

[`img/`](img/) holds the figures used in the top-level README.
