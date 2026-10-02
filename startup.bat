@echo off
setlocal

:: ============================================
:: Navigate to project root (where this .bat lives)
:: ============================================
cd /d "%~dp0"

:: ============================================
:: Python selection:
::   1) bundled runtime 3.14t (installed build): Resource\runtime\python3.14t.exe
::      (python.exe in the runtime image is the GIL build - cannot load cp314t wheels)
::   2) dev venv                               : .venv-py314t\Scripts\python.exe
:: ============================================
set "RUNTIME_PYTHON=%~dp0Resource\runtime\python3.14t.exe"
if not exist "%RUNTIME_PYTHON%" set "RUNTIME_PYTHON=%~dp0Resource\runtime\python.exe"
set "VENV_PYTHON=%~dp0.venv-py314t\Scripts\python.exe"

set "PYTHON="
if exist "%RUNTIME_PYTHON%" set "PYTHON=%RUNTIME_PYTHON%"
if not defined PYTHON if exist "%VENV_PYTHON%" set "PYTHON=%VENV_PYTHON%"

if not defined PYTHON (
    echo [ERROR] No Python runtime found.
    echo   Installed build expects: Resource\runtime\python3.14t.exe
    echo   Dev build expects:      .venv-py314t\Scripts\python.exe
    echo   Dev setup: run Utils\Dev\setup_env.bat
    echo.
    pause
    exit /b 1
)

:: ============================================
:: Runtime flags (free-threading + read-only media safe)
:: ============================================
set "PYTHON_GIL=0"
set "PYTHONNOUSERSITE=1"
set "PYTHONDONTWRITEBYTECODE=1"

:: ============================================
:: Run entry point directly (no activate.bat needed - avoids PATH issues)
:: ============================================
echo Starting MyGameEngine...
"%PYTHON%" -Xgil=0 "%~dp0Application\EntryPoint.py" %*

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application exited with code %errorlevel%
)

pause
endlocal