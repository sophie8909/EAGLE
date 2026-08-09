[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Arguments
)

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source
$cliArguments = @(
    "-m", "eagle", "run",
    "--config", (Join-Path $repoRoot "configs/experiments/microrts.yaml"),
    "--runtime-config", (Join-Path $repoRoot "configs/runtime.yaml")
) + @($Arguments)

Push-Location $repoRoot
try {
    & $python @cliArguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
