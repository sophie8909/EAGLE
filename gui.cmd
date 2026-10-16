@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m eagle gui --open %*
) else (
    python -m eagle gui --open %*
)
if errorlevel 1 pause
