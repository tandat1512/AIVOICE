@echo off
:: Build SmartGen Chrome extension zip for distribution (sideload)
:: Output: dist\smartgen-extension.zip

setlocal enabledelayedexpansion

set ROOT=%~dp0..
set DIST=%ROOT%\dist
set OUT=%DIST%\smartgen-extension.zip
set SRC=%ROOT%\extension

if not exist "%SRC%" (
    echo [ERROR] extension\ directory not found at %SRC%
    exit /b 1
)

if not exist "%DIST%" mkdir "%DIST%"
if exist "%OUT%" del /f "%OUT%"

echo [build] Zipping extension...

powershell -NoProfile -Command ^
  "Get-ChildItem -Path '%SRC%' -Recurse | " ^
  "Where-Object { $_.Name -notmatch '\.DS_Store|Thumbs\.db|\.log$' -and -not $_.PSIsContainer } | " ^
  "Compress-Archive -DestinationPath '%OUT%' -Force"

if errorlevel 1 (
    echo [ERROR] Zip failed
    exit /b 1
)

echo [OK] Extension zipped to: %OUT%
