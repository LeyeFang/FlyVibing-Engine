@echo off
setlocal

:: ============================================
:: Navigate to project root (where this .bat lives)
:: ============================================
cd /d "%~dp0"

:: ============================================
:: Verify virtual environment exists
:: ============================================
set "VENV_PYTHON=%~dp0.venv-py314t\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Virtual environment not found: .venv-py314t\
    echo.
    echo Please run the setup script first:
    echo   Scripts\generate_venv.bat
    echo.
    pause
    exit /b 1
)

:: ============================================
:: Run entry point directly with venv Python
:: (no activate.bat needed — avoids PATH issues)
:: ============================================
echo Starting MyGameEngine...
"%VENV_PYTHON%" -Xgil=0 "%~dp0Application\EntryPoint.py"

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application exited with code %errorlevel%
)

pause
endlocal