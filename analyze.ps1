[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Arguments
)

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source
$remaining = @($Arguments)
$cliArguments = @("-m", "eagle", "analyze", "--runtime-config", (Join-Path $repoRoot "configs/runtime.yaml"))

if ($remaining.Count -eq 0 -or $remaining[0] -eq "--latest") {
    if ($remaining.Count -eq 0) {
        $cliArguments += "--latest"
    } else {
        $cliArguments += $remaining
    }
} else {
    $runDir = $remaining[0]
    $remaining = if ($remaining.Count -gt 1) { $remaining[1..($remaining.Count - 1)] } else { @() }
    if (-not [IO.Path]::IsPathRooted($runDir)) {
        $runDir = [IO.Path]::GetFullPath((Join-Path (Get-Location) $runDir))
    }
    $cliArguments += @("--run-dir", $runDir) + $remaining
}

Push-Location $repoRoot
try {
    & $python @cliArguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
