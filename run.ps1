$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectDir

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
    & ".venv\Scripts\python.exe" -m pip install -e .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& ".venv\Scripts\python.exe" -m japan_drop_radar collect
exit $LASTEXITCODE
