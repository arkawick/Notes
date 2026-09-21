# Bootstrap the local CMWEB instance from scratch.
#
#   .\setup.ps1            build everything (keeps an existing database)
#   .\setup.ps1 -Fresh     delete the database first and rebuild it
#
# Nothing outside local-cmweb\ is written to: cmweb-project, cmweb-app and
# cmweb-scripts are read-only inputs.

param([switch]$Fresh)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

Write-Host '== 1/5  virtualenv' -ForegroundColor Cyan
if (-not (Test-Path $py)) {
    python -m venv .venv
    & $py -m pip install --upgrade pip --quiet
} else {
    Write-Host '   .venv already present'
}

Write-Host '== 2/5  dependencies' -ForegroundColor Cyan
& $py -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

if ($Fresh) {
    Write-Host '== 3/5  removing existing database' -ForegroundColor Cyan
    Remove-Item var\cmweb_local.sqlite3* -Force -ErrorAction SilentlyContinue
} else {
    Write-Host '== 3/5  keeping existing database (use -Fresh to reset)' -ForegroundColor Cyan
}

Write-Host '== 4/5  migrate' -ForegroundColor Cyan
# --skip-checks is required: Django runs system checks before migrate, and the
# checks import the URLconf, which reaches modules that query the database at
# import time (e.g. paginate_by = Parameter.get_int(...) at class scope). On an
# empty database that fails before any table exists.
& $py manage.py migrate --noinput --skip-checks
if ($LASTEXITCODE -ne 0) { throw 'migrate failed' }

Write-Host '== 5/5  sample data' -ForegroundColor Cyan
& $py scripts\load_sample_data.py
if ($LASTEXITCODE -ne 0) { throw 'loading sample data failed' }

& $py scripts\post_setup.py
if ($LASTEXITCODE -ne 0) { throw 'post-setup failed' }

Write-Host ''
Write-Host 'Ready. Start the server with:  .\run.ps1' -ForegroundColor Green
