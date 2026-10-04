@echo off
rem Finishes the pair dev run (case 15 only; resumable), then held-out set 5,
rem which certifies pair pooling. Held-out 5 is SCORED ONCE - never tune on it.
rem Run from a NORMAL terminal with Chrome / VS Code closed: Claude Code kills
rem long jobs under memory pressure. Resumable: finished cases are skipped.
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
set PRAMANA_ABLATE=

echo [1/2] dev, pair on: finish the remaining case
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture tests/fixtures/phase2_testset.json --out pair_dev >> docs\pair_dev.log 2>&1
venv\Scripts\python.exe scripts\score_runs.py tests/fixtures/phase2_testset.json docs\dual_dev_runs.jsonl docs\pair_dev_runs.jsonl

echo [2/2] held-out 5, scored once
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture tests/fixtures/heldout_5.json --out heldout_5 >> docs\heldout_5.log 2>&1
venv\Scripts\python.exe scripts\score_runs.py tests/fixtures/heldout_5.json docs\heldout_5_runs.jsonl
echo All done. Tell Claude.
pause
