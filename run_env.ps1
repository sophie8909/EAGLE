[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "restart", "status", "check")]
    [string] $Command = "start"
)

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source
$cliArguments = @(
    "-m", "eagle", "runtime", $Command,
    "--config", (Join-Path $repoRoot "configs/runtime.yaml")
)

Push-Location $repoRoot
try {
    & $python @cliArguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
