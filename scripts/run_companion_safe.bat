@echo off
rem Finishes the companion-offence evaluation WITHOUT the 2026-10-10 freeze.
rem
rem What went wrong: from IL-TUR doc 65 Ollama (auto-updated that morning to 0.40.2)
rem failed to load the model for lack of memory, could not kill its own failed
rem processes ("TerminateProcess: Access is denied"), and the runner kept asking
rem for more loads until the laptop froze. Now:
rem   - eval_lsi.py stops at the first error, after 8 documents, or when < 2 GB RAM is free
rem   - this file restarts Ollama from clean (killing leftover llama-server.exe) between batches
rem   - Ollama is started as a bare server, so its tray app cannot auto-update mid-run
rem
rem Steps:
rem   [1/3] dev fixtures, companion OFF, on the new Ollama -> docs\textfix_dev_v040_runs.jsonl
rem         (the old baseline ran on Ollama 0.35.1, so the first comparison mixed two changes)
rem   [2/3] dev fixtures, companion ON, second run -> docs\companion_dev2_runs.jsonl (noise)
rem   [3/3] IL-TUR LSI dev: resume docs\iltur_lsi_dev_100_companion.jsonl in batches of 8
rem
rem Close Chrome / VS Code / Claude Code first. About 2 hours. Safe to stop with
rem Ctrl+C and re-run: every step resumes or is short.
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
set PF=tests/fixtures/phase2_testset.json
set LOG=docs\companion_safe.log

echo [1/3] dev fixtures, companion off - progress in %LOG%
call :restart_ollama
set PRAMANA_ABLATE=companion,actveto
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out textfix_dev_v040 >> %LOG% 2>&1

echo [2/3] dev fixtures, companion on - progress in %LOG%
call :restart_ollama
set PRAMANA_ABLATE=
venv\Scripts\python.exe -u scripts\eval_broad.py --fixture %PF% --out companion_dev2 >> %LOG% 2>&1
venv\Scripts\python.exe scripts\score_runs.py %PF% docs\textfix_dev_new_runs.jsonl docs\textfix_dev_v040_runs.jsonl docs\companion_dev_runs.jsonl docs\companion_dev2_runs.jsonl >> %LOG% 2>&1

echo [3/3] IL-TUR LSI dev, batches of 8 - progress in docs\iltur_lsi_dev_100_companion.log
set /a TRIES=0
:lsi
set /a TRIES+=1
if %TRIES% gtr 25 (
    echo Gave up after 25 batches - tell Claude.
    goto end
)
call :restart_ollama
venv\Scripts\python.exe -u scripts\eval_lsi.py --split dev --n 100 --tag companion --max-new 8 >> docs\iltur_lsi_dev_100_companion.log 2>&1
if errorlevel 3 (
    echo    batch %TRIES% done, restarting Ollama
    goto lsi
)
if errorlevel 1 (
    echo eval_lsi crashed - see the log, tell Claude.
    goto end
)
venv\Scripts\python.exe -c "print(open(r'docs\iltur_lsi_dev_100_companion.log',encoding='utf-8',errors='replace').read()[-1500:])"
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
