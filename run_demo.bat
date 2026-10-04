@echo off
rem Pramana demo: starts the FastAPI backend and the Streamlit frontend.
rem Needs Ollama running with qwen3.5:4b pulled. Close Chrome tabs / VS Code if
rem memory is tight: a live analysis loads a 3.4GB model.
cd /d D:\nayasetu
set HF_HUB_OFFLINE=1
start "Pramana API" venv\Scripts\python.exe -m uvicorn src.api.main:app --port 8000
venv\Scripts\python.exe -m streamlit run app\streamlit_app.py --server.headless false
