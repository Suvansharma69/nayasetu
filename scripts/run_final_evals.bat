@echo off
rem Final evaluations for the hardening pass. Run from a NORMAL terminal (not from
rem inside Claude Code: its memory cleanup kills long jobs it started, and a
rem process launched from its session counts as one). Close Chrome first.
rem Every step is resumable: re-run this file and it skips finished cases.
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
set PF=tests/fixtures/phase2_testset.json

echo [1/4] held-out set 2 (method frozen 2026-09-30: judge advisory) - SCORED ONCE
set PRAMANA_ABLATE=
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture tests/fixtures/heldout_2.json --out heldout_2_hardened > stuff\docs\heldout_2_hardened.log 2>&1

echo [2/4] ablation: exclusion off (for the record)
set PRAMANA_ABLATE=exclude
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out abl_no_exclude > stuff\docs\abl_no_exclude.log 2>&1

echo [3/4] ablation: chargeability off (for the record)
set PRAMANA_ABLATE=chargeability
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out abl_no_chargeability > stuff\docs\abl_no_chargeability.log 2>&1

echo [4/4] ablation: everything off = baseline (for the record)
set PRAMANA_ABLATE=profile,exclude,chargeability,judge
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out abl_baseline > stuff\docs\abl_baseline.log 2>&1

set PRAMANA_ABLATE=
echo ALL DONE > stuff\docs\final_evals_done.flag
echo All done. Tell Claude.
pause
