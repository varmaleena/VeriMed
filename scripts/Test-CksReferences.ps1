param(
    [string]$Drug = "metformin 500 mg tablet"
)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $repoRoot "services/cks"
    & (Join-Path $repoRoot ".venv/Scripts/python.exe") services/cks/live.py --drug $Drug
    if ($LASTEXITCODE -ne 0) { throw "Live CKS reference probe incomplete; inspect docs/cks-verification.json." }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}
