# Pramana

AI-assisted legal research for Indian criminal law. Enter case facts and an offence date. Pramana:
1. picks the code that applies (IPC before 1 July 2024, BNS on or after) with a deterministic router;
2. proposes the sections the facts disclose and **verifies every one against a citation graph** built from ingested statutes and judgments;
3. matches precedent judgments (for BNS charges, also through the IPC predecessor section);
4. drafts defence counter-arguments grounded only in verified material;
5. shows how appeals and petitions on those sections were disposed of.

Everything runs locally: BGE-M3 embeddings, ChromaDB, NetworkX and `qwen3.5:4b` on Ollama. No API keys, and no case facts leave the machine. `CLAUDE.md` is the full design record.

## Demo

Needs `qwen3.5:4b` pulled in Ollama, plus the built index, graph and outcomes table (see "Rebuild" below). The launchers start Ollama themselves if it is not running.

```
run_web.bat
```

This starts the backend on port 8000 and opens `http://127.0.0.1:8000/` in the browser. Describe the case in plain words; the offence date is read from the text (the page asks when it cannot tell). The pipeline diagram and section board update live as each stage really finishes. A live run takes about 1-3 minutes on a 4GB laptop GPU; the saved samples open instantly (`/#sample=<id>` links straight to one). The older Streamlit page is still available through `run_demo.bat`.

| sample | what it shows |
|---|---|
| Motorcycle theft (BNS) | the worked example: BNS 303 verified (up to 3 years; 1 to 5 years on a repeat conviction); precedent comes through IPC 379, because no BNS theft case has reached an appeal yet |
| Group assault (IPC) | common intention (s34) and grievous hurt by a weapon (326) charged; rioting (148) **doubted** - it needs five or more persons, the facts show three; 324 shown as included in 326 |
| Fake job scam (IPC) | cheating (420) and forgery for cheating (468); 417 shown as included in 420 |
| OTP impersonation fraud (BNS) | cheating (318) and cheating by personation (319); forgery and stolen-property sections doubted, each with its reason |
| Knife stabbing (BNS) | attempt to murder (109) and hurt by a dangerous weapon (118); culpable homicide (105) doubted - no death occurred; grievous hurt (117) shown as included in 118(2) |
| Security deposit (civil) | no offence charged; a warning that the facts look civil, with the nearest sections listed for review only |

How to read a report: **verified** = in the citation graph and supported by the facts; **doubted** = verified, but the applicability check doubts it (the reason is shown); **struck through** = a citation the model proposed that the graph rejected.

Tools beside each report, all local: the bare text of any section; an IPC-BNS word diff (`/compare`); punishment (a repeat-conviction range shown apart from the first-offence one) and bail from the official First Schedules; PDF upload of an FIR or order; follow-up questions answered only from the report; precedent summaries; a printable research memo.

API: `POST /analyze {"facts": "...", "offence_date": "YYYY-MM-DD"}`, `POST /jobs` + `GET /jobs/{id}` for live progress, `GET /health`.

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

- **The citation check holds; the choice of sections is the weak part.** No invented section number has reached a report in any evaluation. But the model often proposes extra sections that exist and do not apply: about 40% of charged sections are relevant on the development set, and fewer on real court orders. The applicability check marks many extras as doubted, not all.
- **Below the state of the art on the standard benchmark.** On IL-TUR statute identification (100 dev documents) macro-F1 is 9.8, against 28.1 for the best supervised model, which is trained on that task; Pramana is not. Details in `docs/evaluation_results.md`, reproducible with `scripts/eval_lsi.py`.
- **Works best on a statement of facts.** Pasted court orders are reduced to their allegations first; orders that state none are declined rather than charged.
- **Analytics are appeal outcomes, not conviction rates.** Sentence ranges are not extracted.
- **Legal labels and the IPC-BNS mapping were reviewed by Claude, not by a lawyer.**
- **Runs are not perfectly repeatable.** The same facts can occasionally give a different extra section on a second run.
- **Speed.** About 1-3 minutes per case, because the 4GB GPU hands off between the embedder and the LLM.

Research aid only, not legal advice.
