param()
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $buildRoot = Join-Path $repoRoot (".phase1-api/" + [guid]::NewGuid().ToString("N"))
    $bundle = Join-Path $buildRoot "bundle"
    New-Item -ItemType Directory -Path $bundle -Force | Out-Null
    $requirements = Join-Path $buildRoot "requirements.txt"
    & uv export --locked --package verimed-api --no-dev --no-emit-workspace --format requirements.txt --no-header --no-annotate --output-file $requirements | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Pinned API dependency export failed" }
    & uv pip install --python-version 3.12 --python-platform aarch64-manylinux_2_28 --only-binary :all: --require-hashes --no-deps --target $bundle --requirements $requirements
    if ($LASTEXITCODE -ne 0) { throw "Linux ARM API wheel installation failed" }
    $target = Join-Path $bundle "app"
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $repoRoot "services/api/app") -Filter "*.py" -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $target
    }
    $migrationTarget = Join-Path $bundle "migrations"
    New-Item -ItemType Directory -Path $migrationTarget -Force | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $repoRoot "services/api/migrations") -Filter "*.sql" -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $migrationTarget
    }
    if (Get-ChildItem -LiteralPath $bundle -Filter "*.pyd" -File -Recurse) { throw "Windows native extension found in Linux bundle" }
    $manifest = [ordered]@{
        runtime = "python3.12"
        architecture = "arm64"
        platform = "manylinux_2_28"
        builtAt = [DateTimeOffset]::UtcNow.ToString("o")
        requirementsSha256 = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash.ToLowerInvariant()
        modules = @{}
    }
    Get-ChildItem -LiteralPath $target -Filter "*.py" -File | ForEach-Object {
        $manifest.modules[$_.Name] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $bundle "build-manifest.json") -Encoding utf8
    Write-Output "API Linux ARM bundle: $bundle"
}
finally { Pop-Location }
