@echo off
rem Pramana web interface: starts the backend and opens the chat page in the browser.
rem Needs Ollama running with qwen3.5:4b pulled. Close Chrome tabs / VS Code if
rem memory is tight: a live analysis loads a 3.4GB model.
rem (The Streamlit app is still available: run_demo.bat.)
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
start "" cmd /c "timeout /t 6 /nobreak >nul && start http://127.0.0.1:8000/"
venv\Scripts\python.exe -m uvicorn src.api.main:app --port 8000
