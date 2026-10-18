@echo off
rem Dev-set ablations (2026-09-29/30). Each run is resumable: it skips cases already
rem in stuff\docs\abl_<name>_runs.jsonl. Run from D:\nayasetu in a normal terminal.
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
set PF=tests/fixtures/phase2_testset.json

set PRAMANA_ABLATE=profile
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out abl_no_profile > stuff\docs\abl_no_profile.log 2>&1
set PRAMANA_ABLATE=exclude
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out abl_no_exclude > stuff\docs\abl_no_exclude.log 2>&1
set PRAMANA_ABLATE=chargeability
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out abl_no_chargeability > stuff\docs\abl_no_chargeability.log 2>&1
set PRAMANA_ABLATE=profile,exclude,chargeability,judge
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out abl_baseline > stuff\docs\abl_baseline.log 2>&1
set PRAMANA_ABLATE=
echo ALL ABLATIONS DONE > stuff\docs\abl_done.flag
