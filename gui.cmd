@echo off
setlocal DisableDelayedExpansion
set "eagle_root=%~dp0"
set "eagle_wsl_cd="
if "%eagle_root:~0,2%"=="\\" (
    set eagle_wsl_cd=--cd "%eagle_root%."
) else (
    rem WSL inherits the Windows working directory for drive-letter checkouts.
    pushd "%eagle_root%" || exit /b 1
)

set "eagle_wsl_state="
rem WSL returns LF-only lines. Filter by prefix and check the exact state below.
for /f "delims=" %%S in ('wsl.exe %eagle_wsl_cd% -e /bin/sh -c "if test -f pyproject.toml; then if test -x .venv-wsl/bin/python; then echo .venv-wsl/bin/python; elif test -x .venv/bin/python; then echo .venv/bin/python; else echo EAGLE_NO_LINUX_PYTHON; fi; else echo EAGLE_BAD_CHECKOUT; fi" 2^>nul ^| findstr.exe /b /c:".venv-wsl/bin/python" /c:".venv/bin/python" /c:"EAGLE_NO_LINUX_PYTHON" /c:"EAGLE_BAD_CHECKOUT"') do set "eagle_wsl_state=%%S"
if "%eagle_wsl_state%"==".venv-wsl/bin/python" goto launch
if "%eagle_wsl_state%"==".venv/bin/python" goto launch

set "eagle_exit=1"
if "%eagle_wsl_state%"=="EAGLE_NO_LINUX_PYTHON" (
    echo [EAGLE] Create the Linux virtual environment from WSL in this checkout.
    echo     python3 -m venv .venv-wsl
    echo     .venv-wsl/bin/python -m pip install -e .
) else if "%eagle_wsl_state%"=="EAGLE_BAD_CHECKOUT" (
    echo [EAGLE] The default WSL distribution could not find this EAGLE checkout.
    echo     Check the project path from WSL with wsl.exe -e /bin/pwd
) else (
    echo [EAGLE] WSL could not start the default Linux distribution.
    echo     Run wsl.exe --list --verbose and wsl.exe --status in PowerShell.
    echo     For a new WSL installation, see docs/operations/running_eagle.md.
)
goto finish

:launch
wsl.exe %eagle_wsl_cd% -e "%eagle_wsl_state%" -m eagle gui --open %*
set "eagle_exit=%errorlevel%"

:finish
if not "%eagle_root:~0,2%"=="\\" popd
exit /b %eagle_exit%
