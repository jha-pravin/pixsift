# Builds dist\PixSift\PixSift.exe. Run in PowerShell from the repo: .\packaging\build_windows.ps1
# Prerequisites: Python 3.11+ and Node.js 20+. WebView2 ships with Windows 10/11.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path "$PSScriptRoot\.."
$Venv = "$Root\backend\.venv"
if (-not (Test-Path $Venv)) { py -3 -m venv $Venv }
$Py = "$Venv\Scripts\python.exe"

npm --prefix "$Root\frontend" ci
npm --prefix "$Root\frontend" run build
& $Py -m pip install -q -e "$Root\backend[desktop,build]"
& $Py "$Root\packaging\make_icon.py"
& $Py -m PyInstaller --noconfirm --clean --distpath "$Root\dist" --workpath "$Root\build" "$Root\packaging\pixsift.spec"
Write-Host "Built $Root\dist\PixSift\PixSift.exe"
