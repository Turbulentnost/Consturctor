@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
set "HF_HOME=%~dp0models"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
set "ASR_MODEL=openai/whisper-large-v3"
set "ASR_HOST=127.0.0.1"
set "ASR_PORT=7820"
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade-strategy only-if-needed speechbrain hyperpyyaml
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -u -m uvicorn server:app --host %ASR_HOST% --port %ASR_PORT%
