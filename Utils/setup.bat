@echo off
setlocal enabledelayedexpansion

:: ============================================
:: MyGameEngine 一键环境安装脚本
:: 适用于新电脑首次克隆后的完整环境搭建
:: ============================================

cd /d "%~dp0.."

echo ============================================
echo   MyGameEngine - Environment Setup
echo ============================================
echo.

:: ============================================
:: Step 1: Check Python 3.14t
:: ============================================
echo [1/4] Checking Python 3.14t...

set HAS_PY314T=0
py -3.14t --version >nul 2>nul && set HAS_PY314T=1

if !HAS_PY314T! equ 1 (
    echo   [OK] Python 3.14t found
) else (
    echo   [WARN] Python 3.14t not found locally
)

:: ============================================
:: Step 2: Check uv
:: ============================================
echo [2/4] Checking uv package manager...

where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo   [WARN] uv not found. Attempting to install via pip...
    pip install uv >nul 2>nul
    if %errorlevel% neq 0 (
        echo   [ERROR] Failed to install uv.
        echo   Please install manually: https://docs.astral.sh/uv/getting-started/installation/
        pause
        exit /b 1
    )
    echo   [OK] uv installed via pip
) else (
    echo   [OK] uv found
)

:: If Python 3.14t not found, use uv to install it
if !HAS_PY314T! equ 0 (
    echo   Installing Python 3.14t via uv (this may take a few minutes^)...
    uv python install 3.14t
    if !errorlevel! neq 0 (
        echo   [ERROR] Failed to install Python 3.14t
        pause
        exit /b 1
    )
    echo   [OK] Python 3.14t installed
)

:: ============================================
:: Step 3: Create venv and install dependencies
:: ============================================
echo [3/4] Creating virtual environment and installing dependencies...

set "VENV_PATH=%~dp0..\.venv-py314t"

:: Create venv
uv venv --python 3.14t "%VENV_PATH%"
if !errorlevel! neq 0 (
    echo   [ERROR] Failed to create virtual environment
    pause
    exit /b 1
)
echo   [OK] Virtual environment created

:: Install dependencies using the lock file or pyproject.toml
set "LOCK_FILE=%~dp0uv-py314t.lock"
if exist "%LOCK_FILE%" (
    echo   Installing from lock file (reproducible build^)...
    copy /Y "%LOCK_FILE%" "%~dp0..\uv.lock" >nul
    "%VENV_PATH%\Scripts\python.exe" -m uv sync --no-install-project
    if !errorlevel! neq 0 (
        echo   [ERROR] Dependency installation failed
        echo   Check your network connection and try again.
        del /Q "%~dp0..\uv.lock" 2>nul
        pause
        exit /b 1
    )
    del /Q "%~dp0..\uv.lock" 2>nul
) else (
    echo   No lock file found, resolving from pyproject.toml...
    "%VENV_PATH%\Scripts\python.exe" -m uv sync --no-install-project
    if !errorlevel! neq 0 (
        echo   [ERROR] Dependency installation failed
        echo   Check your network connection and try again.
        pause
        exit /b 1
    )
    echo   Saving lock file for future reproducible builds...
    if exist "%~dp0..\uv.lock" (
        copy /Y "%~dp0..\uv.lock" "%LOCK_FILE%" >nul
        echo   [OK] Saved to %LOCK_FILE%
        del /Q "%~dp0..\uv.lock" 2>nul
    ) else (
        echo   [WARN] uv.lock was not generated, skipping lock file save
    )
)
echo   [OK] Dependencies installed

:: ============================================
:: Step 4: Verify
:: ============================================
echo [4/4] Verifying installation...

"%VENV_PATH%\Scripts\python.exe" -c "import glfw; import OpenGL; import numpy; print('Core modules OK')" >nul 2>nul
if !errorlevel! equ 0 (
    echo   [OK] Core modules verified
) else (
    echo   [WARN] Some core modules may be missing (non-fatal^)
)

echo.
echo ============================================
echo   Setup complete!
echo   Run startup.bat to launch the application.
echo ============================================
pause
endlocal
