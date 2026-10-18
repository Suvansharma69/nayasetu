@echo off
rem Pramana web interface: starts the backend and opens the page in the browser.
rem Starts Ollama itself if it is not already running (qwen3.5:4b must be pulled).
rem Close Chrome tabs / VS Code if memory is tight: a live analysis loads a 3.4GB model.
rem (The Streamlit app is still available: run_demo.bat.)
title Pramana
cd /d "%~dp0"
set HF_HUB_OFFLINE=1
set URL=http://127.0.0.1:8000/
if "%~1"==":waitopen" goto waitopen

echo.
echo   Pramana - verified legal research for Indian criminal law
echo   ---------------------------------------------------------

rem Already running (a second double-click)? Just open it.
curl -s -o nul -m 3 %URL% && (
  echo   Pramana is already running. Opening it in the browser.
  start "" %URL%
  exit /b 0
)

if not exist venv\Scripts\python.exe (
  echo   The Python environment venv\ was not found next to this file.
  echo   See README.md, "Setup".
  pause
  exit /b 1
)

call :ensure_ollama

echo   Starting the server. The page opens in your browser as soon as it is ready.
echo   Keep this window open while you use Pramana. Close it to stop Pramana.
echo.
rem Open the browser only once the server answers, not after a fixed delay.
start "" /b cmd /c ""%~f0" :waitopen"
venv\Scripts\python.exe -m uvicorn src.api.main:app --port 8000 --log-level warning
if errorlevel 1 (
  echo.
  echo   The server stopped with an error, shown above. If port 8000 is used by
  echo   another program, close it and run this file again.
  pause
)
exit /b

:waitopen
rem Runs in the background: poll the page (not /health, which waits on Ollama) for up to 2 minutes, then open it.
for /l %%i in (1,1,120) do (
  curl -s -o nul -m 3 %URL% && (start "" %URL% & exit /b 0)
  ping -n 2 127.0.0.1 >nul
)
exit /b 1

:ensure_ollama
rem `ollama serve`, not the tray app: the tray app installs updates, which change
rem the model runtime (see CLAUDE.md, Known Gotchas 2026-10-10).
curl -s -o nul -m 3 http://127.0.0.1:11434/api/version && exit /b 0
echo   Starting Ollama...
start "Ollama" /min ollama serve
set /a WAITS=0
:wait_ollama
%SystemRoot%\System32\timeout.exe /t 2 /nobreak >nul
set /a WAITS+=1
curl -s -o nul -m 3 http://127.0.0.1:11434/api/version && exit /b 0
if %WAITS% lss 30 goto wait_ollama
echo   Ollama did not start. Saved samples still work; live analysis will not.
exit /b 1
