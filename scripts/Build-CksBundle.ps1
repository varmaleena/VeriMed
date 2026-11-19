param()
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $buildRoot = Join-Path $repoRoot (".phase1-cks/" + [guid]::NewGuid().ToString("N"))
    $bundle = Join-Path $buildRoot "bundle"
    New-Item -ItemType Directory -Path $bundle -Force | Out-Null
    $requirements = Join-Path $buildRoot "requirements.txt"
    & uv export --locked --package verimed-cks --no-dev --no-emit-workspace --format requirements.txt --no-header --no-annotate --output-file $requirements | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Pinned CKS dependency export failed" }
    & uv pip install --python-version 3.12 --python-platform x86_64-manylinux_2_28 --only-binary :all: --require-hashes --no-deps --target $bundle --requirements $requirements
    if ($LASTEXITCODE -ne 0) { throw "Linux CKS wheel installation failed" }
    $source = Join-Path $repoRoot "services/cks/cks"
    $target = Join-Path $bundle "cks"
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    Get-ChildItem -LiteralPath $source -Filter "*.py" -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $target
    }
    $invalid = Get-ChildItem -LiteralPath $bundle -Filter "*.pyd" -File -Recurse
    if ($invalid) { throw "Windows native extension found in Linux bundle" }
    $manifest = [ordered]@{
        runtime = "python3.12"
        architecture = "x86_64"
        platform = "manylinux_2_28"
        builtAt = [DateTimeOffset]::UtcNow.ToString("o")
        requirementsSha256 = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash.ToLowerInvariant()
        modules = @{}
    }
    Get-ChildItem -LiteralPath $target -Filter "*.py" -File | ForEach-Object {
        $manifest.modules[$_.Name] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $bundle "build-manifest.json") -Encoding utf8
    Write-Output "CKS Linux bundle: $bundle"
    Write-Output "Set VERIMED_CKS_BUNDLE to that directory for synthesis/deployment."
}
finally {
    Pop-Location
}
