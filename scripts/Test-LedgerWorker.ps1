param([string]$AwsProfile = 'default', [string]$Region = 'us-east-1')
$ErrorActionPreference = 'Stop'
$workspace = Split-Path $PSScriptRoot -Parent
Push-Location -LiteralPath $workspace
try {
  $env:AWS_PROFILE = $AwsProfile
  $env:AWS_REGION = $Region
  $env:PYTHONPATH = Join-Path $workspace 'services/api'
  & .\.venv\Scripts\python.exe services/api/tests/live_ledger_worker.py
  if ($LASTEXITCODE -ne 0) { throw 'Deployed ledger worker checks failed' }
} finally { Pop-Location }
