@echo off
rem IL-TUR Legal Statute Identification, DEV split, 100 documents (seeded sample).
rem Decisions may be made on these results; the TEST split is run once, later,
rem after every decision is made (scripts\eval_lsi.py --split test).
rem
rem Run from a NORMAL terminal with Chrome / VS Code closed: Claude Code kills
rem long jobs under memory pressure. About 3 hours (~100 s a document, longer
rem ones up to several minutes). Resumable: re-run this file and finished
rem documents are skipped.
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
set PRAMANA_ABLATE=

echo IL-TUR LSI dev, 100 documents - progress in docs\iltur_lsi_dev_100.log
venv\Scripts\python.exe -u scripts\eval_lsi.py --split dev --n 100 >> docs\iltur_lsi_dev_100.log 2>&1
venv\Scripts\python.exe -c "print(open(r'docs\iltur_lsi_dev_100.log',encoding='utf-8',errors='replace').read()[-1500:])"
echo All done. Tell Claude.
pause
