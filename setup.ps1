[CmdletBinding()]
param(
    [switch]$ToolsOnly,
    [switch]$WithEditor
)

$ErrorActionPreference = 'Stop'

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program failed (exit $LASTEXITCODE)."
    }
}

function Install-Package {
    param([string]$Id)
    $PSNativeCommandUseErrorActionPreference = $false
    & winget.exe install --id $Id --exact --source winget --architecture x64 --silent --no-upgrade --accept-package-agreements --accept-source-agreements --disable-interactivity
    # WinGet can return UPDATE_NOT_APPLICABLE or PACKAGE_ALREADY_INSTALLED.
    if ($LASTEXITCODE -notin @(0, 0x8A15002B, 0x8A150061)) {
        throw "WinGet could not install $Id (exit $LASTEXITCODE)."
    }
    $env:Path = ((
        $env:Path,
        [Environment]::GetEnvironmentVariable('Path', 'Machine'),
        [Environment]::GetEnvironmentVariable('Path', 'User')
    ) -split ';' | Select-Object -Unique) -join ';'
}

function Get-VerifiedDownload {
    param([string]$Url, [string]$Destination, [string]$Sha256)
    if (Test-Path -LiteralPath $Destination) {
        if ((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash -ne $Sha256) {
            throw "SHA256 mismatch: $Destination. Move it aside and rerun setup."
        }
        return
    }

    $partial = "$Destination.part"
    try {
        # Schannel can continue when a revocation server is offline. The pinned hash still gates installation.
        Invoke-Checked 'curl.exe' @(
            '--fail', '--location', '--retry', '3', '--ssl-revoke-best-effort', '--output', $partial, $Url
        )
        if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $Sha256) {
            throw "SHA256 mismatch for $Url."
        }
        Move-Item -LiteralPath $partial -Destination $Destination
    }
    finally {
        if (Test-Path -LiteralPath $partial) {
            Remove-Item -LiteralPath $partial
        }
    }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
        throw 'This installer requires x64 Windows with a 64-bit PowerShell.'
    }
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw 'Install Microsoft App Installer first. See setup.md.'
    }

    Write-Host 'Installing EAGLE tools and Python dependencies...'
    if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
        Install-Package 'Git.Git'
    }
    if (-not (Get-Command javac.exe -ErrorAction SilentlyContinue) -or (javac.exe -version) -notmatch '^javac 17(\.|$)') {
        Install-Package 'EclipseAdoptium.Temurin.17.JDK'
        $jdk = Get-ChildItem "$env:ProgramFiles\Eclipse Adoptium" -Directory -Filter 'jdk-17*' |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        $env:Path = "$($jdk.FullName)\bin;$env:Path"
    }
    Invoke-Checked 'java.exe' @('-version')
    Invoke-Checked 'javac.exe' @('-version')

    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        $pythonVersions = if ($launcher) { & $launcher.Source --list }
        if ($pythonVersions -match '^\s*-V:3\.13(\s|$)') {
            Invoke-Checked $launcher.Source @('-3.13', '-m', 'venv', '.venv')
        }
        elseif ($pythonVersions -match '^\s*-V:3\.12(\s|$)') {
            Invoke-Checked $launcher.Source @('-3.12', '-m', 'venv', '.venv')
        }
        else {
            Install-Package 'Python.Python.3.13'
            Invoke-Checked 'py.exe' @('-3.13', '-m', 'venv', '.venv')
        }
    }
    Invoke-Checked $venvPython @('-m', 'pip', 'install', '-e', '.')
    Invoke-Checked $venvPython @('-m', 'pip', 'check')

    Write-Host 'Building MicroRTS and its four pinned opponents...'
    Invoke-Checked $venvPython @('scripts/setup_final_test_opponents.py')
    Invoke-Checked $venvPython @('scripts/setup_allibot.py')

    if ($WithEditor) {
        if (-not (Get-Command code.cmd -ErrorAction SilentlyContinue)) {
            Install-Package 'Microsoft.VisualStudioCode'
        }
        Invoke-Checked 'code.cmd' @('--install-extension', 'ms-python.python')
        Invoke-Checked 'code.cmd' @('--install-extension', 'vscjava.vscode-java-pack')
    }

    if (-not $ToolsOnly) {
        Write-Host 'Installing llama.cpp b10236 and Qwen3.5-9B...'
        Install-Package 'Microsoft.VCRedist.2015+.x64'
        $assets = Join-Path $PSScriptRoot 'experiment_env\model'
        $runtime = Join-Path $assets 'llama.cpp-b10236-win-cuda-12.4-x64'
        $server = Join-Path $runtime 'llama-server.exe'
        if (-not (Test-Path -LiteralPath $server)) {
            $downloads = Join-Path $assets '.setup-downloads'
            New-Item -ItemType Directory -Path $downloads -Force | Out-Null
            $release = 'https://github.com/ggml-org/llama.cpp/releases/download/b10236'
            $cudaZip = Join-Path $downloads 'cudart-llama-bin-win-cuda-12.4-x64.zip'
            $llamaZip = Join-Path $downloads 'llama-b10236-bin-win-cuda-12.4-x64.zip'
            Get-VerifiedDownload "$release/cudart-llama-bin-win-cuda-12.4-x64.zip" $cudaZip '8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6'
            Get-VerifiedDownload "$release/llama-b10236-bin-win-cuda-12.4-x64.zip" $llamaZip '0e9aaf22bd39e667490e32d8d58cb23999a798d606a62f46663ba97b005219ba'
            Expand-Archive -LiteralPath $cudaZip -DestinationPath $runtime -Force
            Expand-Archive -LiteralPath $llamaZip -DestinationPath $runtime -Force
        }
        $devices = Invoke-Checked $server @('--list-devices')
        if (-not ($devices -match '^\s*CUDA\d+:')) {
            throw 'llama-server cannot see an NVIDIA CUDA GPU. Install the NVIDIA driver listed in setup.md and rerun.'
        }
        $modelDirectory = Join-Path $assets 'qwen3-5-9b-ud-q4-k-xl-q4-k-xl-bbcc0f54'
        New-Item -ItemType Directory -Path $modelDirectory -Force | Out-Null
        $modelUrl = 'https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/24fadba/Qwen3.5-9B-UD-Q4_K_XL.gguf'
        Get-VerifiedDownload $modelUrl (Join-Path $modelDirectory 'model.gguf') '6f5d30666c2d8ae16a306e616d95341dcf3cc46810df84d7e6f5a7d1e4c1b293'
    }

    Invoke-Checked $venvPython @('-m', 'eagle', 'experiment', '--help') | Out-Null
    Write-Host 'Windows tools are installed. See setup.md for WSL setup before opening gui.cmd.'
}
finally {
    Pop-Location
}
