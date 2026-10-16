$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python venv creation failed' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
if (-not (Test-Path -LiteralPath 'node_modules\@neutralinojs\neu')) {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Node dependency installation failed' }
}
if (-not (Test-Path -LiteralPath 'bin\neutralino-win_x64.exe')) {
    npm.cmd run update
    if ($LASTEXITCODE -ne 0) { throw 'Neutralino runtime download failed' }
}
npm.cmd start
