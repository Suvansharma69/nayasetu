@echo off
rem Dev comparison for the 2026-10-03 changes. Run from a NORMAL terminal with
rem Chrome / VS Code closed: Claude Code kills long jobs under memory pressure.
rem Resumable: re-run this file and finished cases are skipped.
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
set PF=tests/fixtures/phase2_testset.json

echo [1/2] dev baseline: same code, new switches OFF (dual, punish)
set PRAMANA_ABLATE=dual,punish
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out gpu_base_dev >> docs\gpu_base_dev.log 2>&1

echo [2/2] dev: all changes ON
set PRAMANA_ABLATE=
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out dual_dev >> docs\dual_dev.log 2>&1

venv\Scripts\python.exe scripts\score_runs.py %PF% docs\gpu_base_dev_runs.jsonl docs\dual_dev_runs.jsonl
echo All done. Tell Claude.
pause
