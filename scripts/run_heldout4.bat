@echo off
rem Held-out set 4: certifies the 2026-10-03 changes (guardrail review list,
rem punishing section, dual candidate list). SCORED ONCE - never tune on it.
rem Run from a NORMAL terminal with Chrome / VS Code closed. Resumable.
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
set PRAMANA_ABLATE=
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture tests/fixtures/heldout_4.json --out heldout_4 >> docs\heldout_4.log 2>&1
venv\Scripts\python.exe scripts\score_runs.py tests/fixtures/heldout_4.json docs\heldout_4_runs.jsonl
echo All done. Tell Claude.
pause
