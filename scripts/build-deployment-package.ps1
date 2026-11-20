# Assemble a folder that contains the application and its Python wheels.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$package = Join-Path $root "dist\stop-work-order-monitor"
if (Test-Path $package) {
    Remove-Item -Recurse -Force $package
}
New-Item -ItemType Directory -Force -Path (Join-Path $package "wheels") | Out-Null

$files = @(
    "requirements.txt",
    "pyproject.toml",
    ".env.example",
    "README.md"
)
foreach ($file in $files) {
    Copy-Item $file $package
}
Copy-Item "src" (Join-Path $package "src") -Recurse
Copy-Item "config" (Join-Path $package "config") -Recurse
Copy-Item "scripts" (Join-Path $package "scripts") -Recurse

python -m pip download -r requirements.txt -d (Join-Path $package "wheels")
if (-not $?) {
    throw "Could not download Python dependencies into the deployment package."
}

@"
Install on a machine that already has Python 3.11+ and ODBC Driver 18 for SQL Server:

    python -m pip install --no-index --find-links=wheels -r requirements.txt
    python -m pip install --no-index --no-deps -e .
    copy .env.example .env
    python -m stop_work_monitor --once
"@ | Set-Content -Path (Join-Path $package "INSTALL.txt") -Encoding utf8

Write-Output "Deployment package written to $package"
