param(
    [Parameter(Mandatory)][string]$BundlePath,
    [string]$AwsProfile = "default",
    [string]$Region = "us-east-1"
)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$bundle = (Resolve-Path -LiteralPath $BundlePath).Path
$manifest = Get-Content (Join-Path $bundle "build-manifest.json") -Raw | ConvertFrom-Json
if ($manifest.architecture -ne "arm64" -or $manifest.runtime -ne "python3.12") {
    throw "A verified ARM Python 3.12 API bundle is required"
}
foreach ($module in $manifest.modules.PSObject.Properties) {
    $bundled = (Get-FileHash -LiteralPath (Join-Path $bundle ("app/" + $module.Name)) -Algorithm SHA256).Hash.ToLowerInvariant()
    $source = (Get-FileHash -LiteralPath (Join-Path $repoRoot ("services/api/app/" + $module.Name)) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($bundled -ne $module.Value -or $source -ne $module.Value) { throw "The API bundle is stale or its source integrity check failed" }
}
$worklistJson = aws cloudformation describe-stacks --stack-name CellWorklist --profile $AwsProfile --region $Region --output json
if ($LASTEXITCODE -ne 0) { throw "The existing worklist stack could not be read" }
$worklist = ($worklistJson | ConvertFrom-Json).Stacks[0]
$tags = @{}
foreach ($tag in $worklist.Tags) { $tags[$tag.Key] = $tag.Value }
if ($tags.Project -ne "verimed" -or $tags.Env -ne "dev" -or $tags.Tenant -ne "a") {
    throw "This deployment entry point requires the tagged dev cell a"
}
$functionName = ($worklist.Outputs | Where-Object OutputKey -EQ "ApiFunctionName").OutputValue
$settingsJson = aws lambda get-function-configuration --function-name $functionName --profile $AwsProfile --region $Region --query 'Environment.Variables.{Client:COGNITO_CLIENT_ID,Tenant:TENANT_ID,FhirExpiry:FHIR_EXPIRES_AT}' --output json
if ($LASTEXITCODE -ne 0) { throw "Current non-secret API configuration could not be read" }
$settings = $settingsJson | ConvertFrom-Json
if (-not $settings.Client -or -not $settings.Tenant) { throw "Existing tenant/client bindings are required" }
$identityJson = aws cloudformation describe-stacks --stack-name CellIdentity --profile $AwsProfile --region $Region --output json
if ($LASTEXITCODE -ne 0) { throw "The existing identity stack could not be read" }
$identity = ($identityJson | ConvertFrom-Json).Stacks[0]
$issuer = ($identity.Outputs | Where-Object OutputKey -EQ "Issuer").OutputValue
if (-not $issuer) { throw "The existing Cognito issuer is required" }
$identityClient = ($identity.Outputs | Where-Object OutputKey -EQ "ClientId").OutputValue
if ($identityClient -ne $settings.Client) { throw "Identity/API client bindings differ; resolve them before deployment" }
$expiry = $null
if ($settings.FhirExpiry) {
    # Recent PowerShell versions deserialize ISO timestamps as DateTime objects.
    # Normalize without locale-dependent string conversion.
    if ($settings.FhirExpiry -is [DateTime]) { $expiry = [DateTimeOffset]::new($settings.FhirExpiry).ToUniversalTime() }
    elseif ($settings.FhirExpiry -is [DateTimeOffset]) { $expiry = $settings.FhirExpiry.ToUniversalTime() }
    else { $expiry = [DateTimeOffset]::Parse([string]$settings.FhirExpiry, [Globalization.CultureInfo]::InvariantCulture).ToUniversalTime() }
}
if ($expiry -and $expiry -gt [DateTimeOffset]::UtcNow) {
    throw "An active FHIR window must be preserved by its full deployment configuration; use this entry point after expiry"
}
$values = @{
    AWS_PROFILE = $AwsProfile; AWS_REGION = $Region
    VERIMED_CELL_ACCOUNT = $worklist.StackId.Split(':')[4]
    VERIMED_API_BUNDLE = $bundle; VERIMED_TENANT_ID = $settings.Tenant
    AUTH_COGNITO_ID = $settings.Client; AUTH_COGNITO_ISSUER = $issuer
    VERIMED_FHIR_EXPIRES_AT = $(if ($expiry) { $expiry.ToString("o") } else { $null })
    GOMAXPROCS = "2"; GOMEMLIMIT = "512MiB"
}
$previous = @{}
foreach ($name in $values.Keys) { $previous[$name] = [Environment]::GetEnvironmentVariable($name); [Environment]::SetEnvironmentVariable($name, $values[$name]) }
# The expired datastore was deleted. Keep its expiry signal, not stale data permissions.
foreach ($name in @("FHIR_ENDPOINT", "FHIR_DATASTORE_ARN", "FHIR_KMS_KEY_ARN")) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name)
    [Environment]::SetEnvironmentVariable($name, $null)
}
$output = Join-Path $repoRoot (".phase1-api/tracing-" + [guid]::NewGuid().ToString("N"))
Push-Location (Join-Path $repoRoot "infra/cdk")
try {
    & node node_modules/typescript/bin/tsc
    if ($LASTEXITCODE -ne 0) { throw "CDK compilation failed" }
    & node node_modules/aws-cdk/bin/cdk synth CellWorklist --app "node dist/app.js" -c cellWorklist=true -c cellObservability=true -c cellTracing=true --output $output --quiet
    if ($LASTEXITCODE -ne 0) { throw "Tracing synthesis/security checks failed" }
    & node node_modules/aws-cdk/bin/cdk deploy CellWorklist --app $output --require-approval never --profile $AwsProfile
    if ($LASTEXITCODE -ne 0) { throw "Tracing deployment failed; inspect CloudFormation status" }
}
finally {
    Pop-Location
    foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name]) }
}
