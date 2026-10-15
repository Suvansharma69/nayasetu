@echo off
rem IL-TUR Legal Statute Identification, TEST split, 100 documents (seeded sample).
rem Run ONCE, after every decision was made on the dev split. Started 2026-10-15;
rem 17/100 finished before Claude Code stopped it for low memory.
rem
rem Run from a NORMAL terminal with Chrome / VS Code closed: Claude Code kills
rem long jobs under memory pressure. About 3-4 hours. Resumable: re-run this
rem file and finished documents are skipped.
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
set PRAMANA_ABLATE=

echo IL-TUR LSI test, 100 documents - progress in docs\iltur_lsi_test_100.log
venv\Scripts\python.exe -u scripts\eval_lsi.py --split test --n 100 >> docs\iltur_lsi_test_100.log 2>&1
venv\Scripts\python.exe -c "print(open(r'docs\iltur_lsi_test_100.log',encoding='utf-8',errors='replace').read()[-1500:])"
echo All done. Tell Claude.
pause
