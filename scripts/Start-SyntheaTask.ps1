param(
    [ValidateRange(1, 50)][int]$Population = 50,
    [string]$AwsProfile = "default",
    [string]$Region = "us-east-1",
    [ValidatePattern('^[a-z][a-z0-9-]{0,31}$')][string]$Cell = "a"
)
$ErrorActionPreference = "Stop"
$response = aws cloudformation describe-stacks --stack-name CellSynthea --profile $AwsProfile --region $Region --output json
if ($LASTEXITCODE -ne 0) { throw "The Synthea task stack is unavailable" }
$stack = ($response | ConvertFrom-Json).Stacks[0]
$tags = @{}
foreach ($tag in $stack.Tags) { $tags[$tag.Key] = $tag.Value }
if ($tags.Project -ne "verimed" -or $tags.Env -ne "dev" -or $tags.Tenant -ne $Cell) {
    throw "Generation requires the expected tenant's tagged dev stack"
}
$workflow = ($stack.Outputs | Where-Object OutputKey -EQ "WorkflowArn").OutputValue
if (-not $workflow) { throw "No verified image/task is deployed; build and scan it first" }
$job = [guid]::NewGuid().ToString()
$inputJson = @{ job_id = $job; population = $Population } | ConvertTo-Json -Compress
$repoRoot = Split-Path -Parent $PSScriptRoot
$outputRoot = Join-Path $repoRoot ".phase1-fhir"
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
$inputPath = Join-Path $outputRoot ("generation-" + $job + ".json")
[IO.File]::WriteAllText($inputPath, $inputJson, [Text.UTF8Encoding]::new($false))
$result = aws stepfunctions start-execution --state-machine-arn $workflow --name $job --input ("file://" + $inputPath) --profile $AwsProfile --region $Region --output json
if ($LASTEXITCODE -ne 0) { throw "Synthea execution could not be started" }
$started = $result | ConvertFrom-Json
Write-Output ("Started bounded synthetic generation: " + $started.executionArn)
Write-Output ("Job ID: " + $job + "; population: " + $Population)
Write-Output "This generates an encrypted FHIR input; it does not recreate or extend HealthLake."
