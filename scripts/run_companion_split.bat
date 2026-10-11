@echo off
rem Re-scores the companion-offence rule with its questions asked in a SEPARATE
rem call (nodes.companion_profile), so Node 1's own prompt is the baseline's.
rem Why: docs\evaluation_results.md 6b - inside Node 1's call the questions made
rem the model name more sections (dev precision 41% -> 32-33%), while the LSI
rem gains came from the rule's own proposals.
rem
rem Merge rule, fixed before this run:
rem   dev (vs textfix_dev_v040, same Ollama 0.40.2): recall not below 14/15 and
rem       precision not below 41% - 2 points in BOTH runs
rem   LSI (vs docs\iltur_lsi_dev_100.jsonl): micro-F1 up and macro-F1 not down,
rem       on all 100 and on docs 36-100 (both on 0.40.2)
rem
rem Steps:
rem   [1/3] dev fixtures, run 1 -> docs\companion_split_dev_runs.jsonl
rem   [2/3] dev fixtures, run 2 -> docs\companion_split_dev2_runs.jsonl, then scored
rem   [3/3] IL-TUR LSI dev, 100 docs in batches of 8 -> docs\iltur_lsi_dev_100_companion_split.jsonl
rem
rem Close Chrome / VS Code / Claude Code first. About 3.5 hours. Safe to stop with
rem Ctrl+C and re-run: the LSI step resumes; a dev step re-runs (about 20 min).
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
set PRAMANA_ABLATE=
set PF=tests/fixtures/phase2_testset.json
set LOG=docs\companion_split.log

echo [1/3] dev fixtures, run 1 - progress in %LOG%
call :restart_ollama
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out companion_split_dev >> %LOG% 2>&1

echo [2/3] dev fixtures, run 2 - progress in %LOG%
call :restart_ollama
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out companion_split_dev2 >> %LOG% 2>&1
venv\Scripts\python.exe scripts\score_runs.py %PF% docs\textfix_dev_v040_runs.jsonl docs\companion_dev_runs.jsonl docs\companion_split_dev_runs.jsonl docs\companion_split_dev2_runs.jsonl >> %LOG% 2>&1

echo [3/3] IL-TUR LSI dev, batches of 8 - progress in docs\iltur_lsi_dev_100_companion_split.log
set /a TRIES=0
:lsi
set /a TRIES+=1
if %TRIES% gtr 25 (
    echo Gave up after 25 batches - tell Claude.
    goto end
)
call :restart_ollama
venv\Scripts\python.exe -u scripts\eval_lsi.py --split dev --n 100 --tag companion_split --max-new 8 >> docs\iltur_lsi_dev_100_companion_split.log 2>&1
if errorlevel 3 (
    echo    batch %TRIES% done, restarting Ollama
    goto lsi
)
if errorlevel 1 (
    echo eval_lsi crashed - see the log, tell Claude.
    goto end
)
venv\Scripts\python.exe -c "print(open(r'docs\iltur_lsi_dev_100_companion_split.log',encoding='utf-8',errors='replace').read()[-1500:])"
echo All done. Tell Claude.

:end
taskkill /f /im ollama.exe >nul 2>&1
taskkill /f /im llama-server.exe >nul 2>&1
pause
exit /b

:restart_ollama
taskkill /f /im "ollama app.exe" >nul 2>&1
taskkill /f /im ollama.exe >nul 2>&1
taskkill /f /im llama-server.exe >nul 2>&1
timeout /t 5 /nobreak >nul
start "ollama serve" /min ollama serve
set /a WAITS=0
:wait_ollama
timeout /t 2 /nobreak >nul
set /a WAITS+=1
curl -s http://127.0.0.1:11434/api/version >nul 2>&1 && exit /b 0
if %WAITS% lss 30 goto wait_ollama
echo Ollama did not start - tell Claude.
exit /b 1
