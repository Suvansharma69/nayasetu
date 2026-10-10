@echo off
rem Finishes run_companion.bat, whose IL-TUR half stopped at 78/100 on 2026-10-10
rem (Ollama out of memory from doc 65 on: 14 errored, 22 not reached).
rem   [1/2] IL-TUR LSI dev: resumes docs\iltur_lsi_dev_100_companion.jsonl -
rem         finished documents are skipped, the 14 errored ones are retried.
rem   [2/2] a SECOND dev-fixture run with the companion switch on, into
rem         docs\companion_dev2_runs.jsonl. The first one's precision drop (39% -> 33%)
rem         did not come from rule proposals (the rule fired once, on a 506 already
rem         charged), so this measures how much of it is run-to-run noise.
rem
rem Run from a NORMAL terminal with Chrome / VS Code / Claude Code closed - the last
rem run's errors were out-of-memory. About 1.5 hours. Safe to re-run if interrupted.
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
set PRAMANA_ABLATE=
set PF=tests/fixtures/phase2_testset.json

echo [1/2] IL-TUR LSI dev, resuming - progress in docs\iltur_lsi_dev_100_companion.log
venv\Scripts\python.exe -u scripts\eval_lsi.py --split dev --n 100 --tag companion >> docs\iltur_lsi_dev_100_companion.log 2>&1

echo [2/2] dev fixtures, second companion run - progress in docs\companion_dev2.log
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out companion_dev2 >> docs\companion_dev2.log 2>&1
venv\Scripts\python.exe scripts\score_runs.py %PF% docs\textfix_dev_new_runs.jsonl docs\companion_dev_runs.jsonl docs\companion_dev2_runs.jsonl >> docs\companion_dev2.log 2>&1

venv\Scripts\python.exe -c "print(open(r'docs\iltur_lsi_dev_100_companion.log',encoding='utf-8',errors='replace').read()[-1500:])"
echo All done. Tell Claude.
pause
