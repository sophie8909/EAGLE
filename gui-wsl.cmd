@echo off
wsl.exe --cd "%~dp0." --exec .venv/bin/python -m eagle gui --open %*
