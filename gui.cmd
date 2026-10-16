@echo off
rem Run from the checkout's WSL environment, including Java/WSLg.
wsl.exe --cd "%~dp0." bash -lc "exec .venv/bin/python -m eagle gui --open"
