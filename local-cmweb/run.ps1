# Start the local CMWEB development server.
#
#   .\run.ps1              serve on http://127.0.0.1:8000/
#   .\run.ps1 -Port 8080   serve on another port
#   .\run.ps1 -Anonymous   do not auto-login (see config\middleware_local.py)

param(
    [int]$Port = 8000,
    [switch]$Anonymous
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw 'No .venv found -- run .\setup.ps1 first.' }
if (-not (Test-Path 'var\cmweb_local.sqlite3')) {
    throw 'No database found -- run .\setup.ps1 first.'
}

if ($Anonymous) { $env:CMWEB_LOCAL_AUTOLOGIN = '0' }

Write-Host "CMWEB local  ->  http://127.0.0.1:$Port/" -ForegroundColor Green
Write-Host '  builds     /builds/' -ForegroundColor DarkGray
Write-Host '  commits    /commits/' -ForegroundColor DarkGray
Write-Host '  repos      /repositories/' -ForegroundColor DarkGray
Write-Host '  admin      /admin/' -ForegroundColor DarkGray
Write-Host ''

& $py manage.py runserver "127.0.0.1:$Port"
