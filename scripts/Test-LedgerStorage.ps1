param(
  [string]$AwsProfile = 'default',
  [string]$Region = 'us-east-1',
  [switch]$ApplySchema
)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path $PSScriptRoot -Parent
function Get-StackOutput([string]$StackName, [string]$OutputKey) {
  $result = aws cloudformation describe-stacks --stack-name $StackName --profile $AwsProfile --region $Region --query "Stacks[0].Outputs[?OutputKey=='$OutputKey'].OutputValue | [0]" --output text
  if ($LASTEXITCODE -ne 0 -or -not $result -or $result -eq 'None') { throw "Missing output $OutputKey from $StackName" }
  return $result.Trim()
}
Push-Location -LiteralPath $workspace
try {
  $env:AWS_PROFILE = $AwsProfile
  $env:AWS_REGION = $Region
  $env:PYTHONPATH = Join-Path $workspace 'services/api'
  $env:DATABASE_CLUSTER_ARN = Get-StackOutput CellWorklist ClusterArn
  $env:DATABASE_SECRET_ARN = Get-StackOutput CellWorklist SecretArn
  $env:DATABASE_RUNTIME_SECRET_ARN = Get-StackOutput CellWorklist RuntimeSecretArn
  $env:DATABASE_LEDGER_SECRET_ARN = Get-StackOutput CellWorklist LedgerWriterSecretArn
  $env:LEDGER_SIGNING_KEY_ARN = Get-StackOutput CellLedger SigningKeyArn
  if ($ApplySchema) {
    & .\.venv\Scripts\python.exe services/api/migrate_ledger.py
    if ($LASTEXITCODE -ne 0) { throw 'Ledger migration failed' }
  }
  & .\.venv\Scripts\python.exe services/api/tests/live_ledger_store.py
  if ($LASTEXITCODE -ne 0) { throw 'Live ledger storage checks failed' }
} finally { Pop-Location }
