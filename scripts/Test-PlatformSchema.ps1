param(
    [string]$AwsProfile = "default",
    [string]$Region = "us-east-1",
    [switch]$ApplySchema
)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
function StackOutput([string]$Name) {
    $value = aws cloudformation describe-stacks --stack-name CellWorklist --profile $AwsProfile --region $Region --query "Stacks[0].Outputs[?OutputKey=='$Name'].OutputValue | [0]" --output text
    if ($LASTEXITCODE -ne 0 -or !$value -or $value -eq "None") { throw "Missing CellWorklist output: $Name" }
    return $value.Trim()
}
$previous = @{}
foreach ($name in @("AWS_PROFILE","AWS_REGION","PYTHONPATH","DATABASE_CLUSTER_ARN","DATABASE_SECRET_ARN","DATABASE_RUNTIME_SECRET_ARN")) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}
Push-Location $repoRoot
try {
    $env:AWS_PROFILE = $AwsProfile
    $env:AWS_REGION = $Region
    $env:PYTHONPATH = Join-Path $repoRoot "services/api"
    $env:DATABASE_CLUSTER_ARN = StackOutput "ClusterArn"
    $env:DATABASE_SECRET_ARN = StackOutput "SecretArn"
    $env:DATABASE_RUNTIME_SECRET_ARN = StackOutput "RuntimeSecretArn"
    if ($ApplySchema) {
        & .venv/Scripts/python.exe services/api/migrate_platform.py
        if ($LASTEXITCODE -ne 0) { throw "Platform migration failed; clinical records were not intentionally modified." }
    }
    & .venv/Scripts/python.exe services/api/tests/live_platform_schema.py
    if ($LASTEXITCODE -ne 0) { throw "Live platform schema verification failed." }
}
finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], "Process")
    }
    Pop-Location
}
