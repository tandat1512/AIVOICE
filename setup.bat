@echo off
setlocal enabledelayedexpansion

:: SmartGen Windows setup script
:: Usage: setup.bat
:: Creates .venv, installs deps, copies .env.example → .env

echo.
echo  SmartGen setup (Windows)
echo  ========================
echo.

:: ── Python version check ──────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from https://python.org
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PY_VER%") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)

if %PY_MAJOR% LSS 3 (
    echo [ERROR] Python 3.10+ required. Found: %PY_VER%
    exit /b 1
)
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 10 (
    echo [ERROR] Python 3.10+ required. Found: %PY_VER%
    exit /b 1
)
echo [OK] Python %PY_VER%

:: ── Virtual environment ───────────────────────────────────────────────────────
set VENV=.venv
if not exist "%VENV%\" (
    echo [setup] Creating virtual environment...
    python -m venv %VENV%
    if errorlevel 1 ( echo [ERROR] venv creation failed & exit /b 1 )
) else (
    echo [OK] Virtual environment already exists
)

set PY=%VENV%\Scripts\python.exe
set PIP=%VENV%\Scripts\pip.exe

:: ── PyTorch (CPU by default; edit to add --index-url for CUDA) ────────────────
echo [setup] Installing PyTorch (CPU)...
echo         For CUDA: pip install torch==2.3.1 --index-url https://download.pytorch.org/whl/cu121
%PIP% install --quiet torch==2.3.1
if errorlevel 1 ( echo [ERROR] PyTorch install failed & exit /b 1 )

:: ── Project dependencies ──────────────────────────────────────────────────────
echo [setup] Installing project dependencies...
%PIP% install --quiet -r requirements.txt
if errorlevel 1 ( echo [ERROR] requirements.txt install failed & exit /b 1 )

:: ── Environment file ──────────────────────────────────────────────────────────
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [setup] Created .env from .env.example
    )
) else (
    echo [OK] .env already exists
)

echo.
echo  Setup complete!
echo  ─────────────────────────────────────────────────
echo  Start server:  .\run.ps1 serve
echo  Or:            %PY% -m uvicorn server.main:app --host 0.0.0.0 --port 8000
echo.
