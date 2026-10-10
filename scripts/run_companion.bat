@echo off
rem Companion-offence rule + act veto (branch companion-offences), scored on:
rem   [1/2] the 15 dev fixtures, against docs\textfix_dev_new_runs.jsonl (same code,
rem         both changes absent; the act veto cannot touch fact statements)
rem   [2/2] IL-TUR LSI dev, the SAME 100 documents as docs\iltur_lsi_dev_100.jsonl
rem         (seed 20260927), into docs\iltur_lsi_dev_100_companion.jsonl
rem With both switches off the code is the baseline's exactly (PRAMANA_ABLATE=companion,actveto).
rem
rem Run from a NORMAL terminal with Chrome / VS Code closed: Claude Code kills long
rem jobs under memory pressure. About 3.5 hours. Resumable: re-run this file and
rem finished cases/documents are skipped (errored ones are retried).
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
set PRAMANA_ABLATE=
set PF=tests/fixtures/phase2_testset.json

echo [1/2] dev fixtures, companion rule on - progress in docs\companion_dev.log
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out companion_dev >> docs\companion_dev.log 2>&1
venv\Scripts\python.exe scripts\score_runs.py %PF% docs\textfix_dev_new_runs.jsonl docs\companion_dev_runs.jsonl >> docs\companion_dev.log 2>&1

echo [2/2] IL-TUR LSI dev, 100 documents - progress in docs\iltur_lsi_dev_100_companion.log
venv\Scripts\python.exe -u scripts\eval_lsi.py --split dev --n 100 --tag companion >> docs\iltur_lsi_dev_100_companion.log 2>&1
venv\Scripts\python.exe -c "print(open(r'docs\iltur_lsi_dev_100_companion.log',encoding='utf-8',errors='replace').read()[-1500:])"
echo All done. Tell Claude.
pause
