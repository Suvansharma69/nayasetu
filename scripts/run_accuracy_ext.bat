@echo off
rem Accuracy A/B of 2026-10-07 on 30 UNSEEN external court orders (ext0060-0089).
rem   baseline = the code as merged on main (old IPC text, old definition pairs,
rem              no-facts rule switched off)
rem   current  = completed IPC text + new pairs + no-facts rule
rem Same code in both arms; only data files and one switch differ.
rem
rem Run from a NORMAL terminal with Chrome / VS Code closed: background jobs in a
rem Claude Code session are killed under memory pressure (2026-10-07).
rem Resumable: re-run this file and finished cases are skipped. About 70 minutes.
rem It ALWAYS leaves the current data in place, even if you stop it part-way:
rem re-running it, or just the last block, restores it.
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
set PY=venv\Scripts\python.exe
set B=data\processed\_baseline
if not exist %B%\statutes_ipc_main.jsonl (echo missing %B%\statutes_ipc_main.jsonl & pause & exit /b 1)
if not exist %B%\statutes_ipc_current.jsonl copy /y data\processed\statutes_ipc.jsonl %B%\statutes_ipc_current.jsonl >nul
if not exist %B%\chargeability_current.json copy /y data\mappings\chargeability.json %B%\chargeability_current.json >nul

echo [1/3] BASELINE arm (main's data, no-facts rule off)
copy /y %B%\statutes_ipc_main.jsonl data\processed\statutes_ipc.jsonl >nul
copy /y %B%\chargeability_main.json data\mappings\chargeability.json >nul
%PY% scripts\build_index.py --only ipc_sections
%PY% %B%\dev_cands.py %B%\dev_cands_main.json
set PRAMANA_ABLATE=nofacts
%PY% -u scripts\eval_ext_slice.py docs\accuracy_ext60_base_runs.jsonl 60 30
set PRAMANA_ABLATE=

echo [2/3] CURRENT arm
copy /y %B%\statutes_ipc_current.jsonl data\processed\statutes_ipc.jsonl >nul
copy /y %B%\chargeability_current.json data\mappings\chargeability.json >nul
%PY% scripts\build_index.py --only ipc_sections
%PY% %B%\dev_cands.py %B%\dev_cands_current.json
%PY% -u scripts\eval_ext_slice.py docs\accuracy_ext60_new_runs.jsonl 60 30

echo [3/3] check the current data is in place
fc /b data\processed\statutes_ipc.jsonl %B%\statutes_ipc_current.jsonl >nul && fc /b data\mappings\chargeability.json %B%\chargeability_current.json >nul && echo current data in place
echo All done. Tell Claude.
pause
