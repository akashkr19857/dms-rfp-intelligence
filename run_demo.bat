@echo off
REM DMS RFP Intelligence one-click demo (Windows). Starts the API on :8200 and the dashboard on :3200.
REM Needs: Ollama running with qwen2.5:7b and nomic-embed-text pulled; Node 22; Python 3.11 with requirements.txt.
setlocal
cd /d "%~dp0"
set "PY=%~dp0..\_shared\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo [1/5] Checking Ollama models...
ollama list | findstr /i "qwen2.5:7b" >nul || ollama pull qwen2.5:7b
ollama list | findstr /i "nomic-embed-text" >nul || ollama pull nomic-embed-text

echo [2/5] Public RFPs + sample knowledge base (first run only)...
if not exist "data\rfps\champaign_CCMS.pdf" "%PY%" data\download_data.py
if not exist "data\knowledge_base\01_Company_Profile.docx" "%PY%" data\make_knowledge_base.py

echo [3/5] Indexing documents (first run: about 2 minutes)...
"%PY%" backend\scripts\seed.py

echo [4/5] Starting API on http://localhost:8200 ...
start "RFP Intelligence API" /D "%~dp0backend" "%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8200

echo [5/5] Starting dashboard on http://localhost:3200 ...
cd frontend
if not exist node_modules call npm install
if not exist .next\BUILD_ID call npm run build
start "RFP Intelligence dashboard" /D "%~dp0frontend" cmd /k npm run start
timeout /t 6 >nul
start http://localhost:3200
echo.
echo Open a tender and click "Analyse RFP" (about 10 minutes per 30-page RFP on an RTX 4060 laptop GPU).
endlocal
