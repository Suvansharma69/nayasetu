# Pramana

AI-assisted legal research for Indian criminal law. Enter case facts and an offence date. Pramana:
1. picks the code that applies (IPC before 1 July 2024, BNS on or after) with a deterministic router;
2. proposes the sections the facts disclose and **verifies every one against a citation graph** built from ingested statutes and judgments;
3. matches precedent judgments (for BNS charges, also through the IPC predecessor section);
4. drafts defence counter-arguments grounded only in verified material;
5. shows how appeals and petitions on those sections were disposed of.

Everything runs locally: BGE-M3 embeddings, ChromaDB, NetworkX and `qwen3.5:4b` on Ollama. No API keys, and no case facts leave the machine. `CLAUDE.md` is the full design record.

## Demo

Needs Ollama running with `qwen3.5:4b`, plus the built index, graph and outcomes table (see "Rebuild" below).

```
run_demo.bat
```

This starts the FastAPI backend (port 8000) and opens the Streamlit page. Four sample cases are in the sidebar; **Show saved result** opens their precomputed reports instantly. **Analyse** runs the live pipeline, about 2-3 minutes on a 4GB laptop GPU.

| sample | what it shows |
|---|---|
| Motorcycle theft (BNS) | the worked example: BNS 303 verified; precedent comes from IPC 378/379 because no BNS theft case has reached an appeal yet |
| Group assault (IPC) | common intention (s34) charged; rioting (147/148) and murder (302) marked **doubted**: rioting needs five or more persons, and no death occurred |
| Fake job scam (IPC) | cheating (420) and forgery for cheating (468), with Supreme Court precedent |
| Security deposit (civil) | no offence charged; a warning that the facts look civil, with the nearest sections listed for review only |

How to read a report: **green** = verified in the citation graph and supported by the facts; **amber** = verified but the applicability check doubts it (the reason is shown); **red, struck through** = a citation the model proposed that the graph rejected.

API: `POST /analyze {"facts": "...", "offence_date": "YYYY-MM-DD"}` and `GET /health`.

## Rebuild

```
venv\Scripts\python.exe scripts\build_corpus.py     # data/raw -> data/processed
venv\Scripts\python.exe scripts\build_index.py      # ChromaDB, ~25 min on GPU
venv\Scripts\python.exe scripts\build_graph.py      # citation graph
venv\Scripts\python.exe scripts\build_outcomes.py   # outcomes table for analytics
venv\Scripts\python.exe scripts\run_demo_cases.py   # refresh the saved sample reports
venv\Scripts\python.exe -m pytest tests -q
```

## Known limitations (MVP)

- **Over-charging.** The model often proposes extra sections that exist but do not apply. The applicability check marks many of them as doubted, but not all, and it sometimes doubts a correct one. On held-out sets, about 40% of charged sections are relevant; the right section is charged in 60-67% of held-out cases (100% on the development set).
- **Analytics are appeal outcomes, not conviction rates.** Sentence ranges are not extracted.
- **Legal labels and the IPC-BNS mapping were reviewed by Claude, not by a lawyer.**
- **Not evaluated on IL-TUR yet.** Access to the dataset is pending.
- **Speed.** About 2-3 minutes per case, because the 4GB GPU has to hand off between the embedder and the LLM.

Research aid only, not legal advice.
