@echo off
rem Pramana demo: starts the FastAPI backend and the Streamlit frontend.
rem Starts Ollama itself if it is not already running (qwen3.5:4b must be pulled).
rem Close Chrome tabs / VS Code if memory is tight: a live analysis loads a 3.4GB model.
rem (The main interface is run_web.bat.)
cd /d "%~dp0"
set HF_HUB_OFFLINE=1
call :ensure_ollama
start "Pramana API" venv\Scripts\python.exe -m uvicorn src.api.main:app --port 8000
venv\Scripts\python.exe -m streamlit run app\streamlit_app.py --server.headless false
exit /b

:ensure_ollama
rem `ollama serve`, not the tray app: the tray app installs updates, which change
rem the model runtime (see CLAUDE.md, Known Gotchas 2026-10-10).
curl -s http://127.0.0.1:11434/api/version >nul 2>&1 && exit /b 0
echo Starting Ollama...
start "Ollama" /min ollama serve
set /a WAITS=0
:wait_ollama
%SystemRoot%\System32\timeout.exe /t 2 /nobreak >nul
set /a WAITS+=1
curl -s http://127.0.0.1:11434/api/version >nul 2>&1 && exit /b 0
if %WAITS% lss 30 goto wait_ollama
echo Ollama did not start. Saved samples still work; live analysis will not.
exit /b 1
