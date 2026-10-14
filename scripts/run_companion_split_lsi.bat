@echo off
rem Finishes step [3/3] of run_companion_split.bat only: IL-TUR LSI dev, tag
rem companion_split, resuming from the documents already in
rem docs\iltur_lsi_dev_100_companion_split.jsonl (71 of 100 on 2026-10-14).
rem The dev steps are done and scored (docs\companion_split.log) - not re-run.
rem
rem Refuses to run on any Ollama but 0.40.2: every run this result is compared
rem with used 0.40.2, and the tray app has found 0.40.4 (2026-10-14). Do not
rem accept that update until this finishes.
rem
rem Close Chrome / VS Code / Claude Code first. About 50 minutes. Safe to stop
rem with Ctrl+C and re-run.
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
set PRAMANA_ABLATE=
set LSILOG=docs\iltur_lsi_dev_100_companion_split.log

ollama --version | findstr /c:"0.40.2" >nul
if errorlevel 1 (
    echo Ollama is not 0.40.2 - stopping, tell Claude.
    ollama --version
    goto end
)

echo IL-TUR LSI dev, batches of 8 - progress in %LSILOG%
set /a TRIES=0
:lsi
set /a TRIES+=1
if %TRIES% gtr 15 (
    echo Gave up after 15 batches - tell Claude.
    goto end
)
call :restart_ollama
if errorlevel 1 goto end
venv\Scripts\python.exe -u scripts\eval_lsi.py --split dev --n 100 --tag companion_split --max-new 8 >> %LSILOG% 2>&1
if errorlevel 3 (
    echo    batch %TRIES% done, restarting Ollama
    goto lsi
)
if errorlevel 1 (
    echo eval_lsi crashed - see the log, tell Claude.
    goto end
)
venv\Scripts\python.exe -c "print(open(r'%LSILOG%',encoding='utf-8',errors='replace').read()[-1500:])"
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
