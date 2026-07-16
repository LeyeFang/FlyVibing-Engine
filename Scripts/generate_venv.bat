@echo off
setlocal enabledelayedexpansion

:: ============================================
:: Script dir (Scripts) and project root (resolved to absolute path)
:: ============================================
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%.." || (echo [ERROR] Cannot enter project directory & pause & exit /b 1)
set PROJECT_ROOT=%CD%
cd /d "%SCRIPT_DIR%"

:: Venv paths
set VENV_314=%PROJECT_ROOT%\.venv-py314t
set VENV_PYTHON=%VENV_314%\Scripts\python.exe

:: Lock file paths
set LOCK_314=%SCRIPT_DIR%uv-py314t.lock

:: Navigate to project root
cd /d "%PROJECT_ROOT%"

:: ============================================
:: Check uv is installed
:: ============================================
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] uv not found. Install: https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

echo [INFO] uv found.
echo.

:: ============================================
:: Detect installed Python versions
::   Use 'uv python list --only-installed' to avoid auto-download
:: ============================================
echo [INFO] Checking installed Python versions...

set HAS_PY314T=0

:: Use uv to list only installed pythons, then search for versions
for /f "tokens=1,2" %%a in ('uv python list --only-installed 2^>nul ^| findstr /r /c:"cpython-3\.14"') do (
    echo   Found: %%a %%b
    echo %%a | findstr "3.14" >nul && set HAS_PY314T=1
)

:: Fallback: try 'py' launcher if uv list returned nothing
if !HAS_PY314T! equ 0 (
    py -3.14t --version >nul 2>nul && set HAS_PY314T=1
)

echo [INFO] Python 3.14t : !HAS_PY314T! (1=found, 0=not found^)
echo.

:: If not found, exit
if !HAS_PY314T! equ 0 (
    echo [ERROR] Python 3.14t not found.
    echo   Install with: uv python install 3.14t
    pause
    exit /b 1
)

:setup_314
:: ============================================
:: Setup Python 3.14t venv
:: ============================================
if !HAS_PY314T! equ 0 (
    echo [SKIP] Python 3.14t not found, skipping .venv-py314t.
    goto :done
)

if not exist "%LOCK_314%" (
    echo [WARN] Lock file not found: %LOCK_314%, skipping .venv-py314t.
    goto :done
)

echo ========================================
echo Setting up .venv-py314t (Python 3.14t^)
echo ========================================

echo [CREATE] Creating .venv-py314t (--clear to replace if exists^)...
uv venv --clear --python 3.14t "%VENV_314%"
if !errorlevel! neq 0 (
    echo [ERROR] Failed to create .venv-py314t
    pause
    exit /b 1
)

:: Copy lock file and sync
copy /Y "%LOCK_314%" "%PROJECT_ROOT%\uv.lock" >nul
echo [SYNC] Installing dependencies (may take a few minutes^)...
cmd /c "set VIRTUAL_ENV=%VENV_314%&& uv sync --python "%VENV_PYTHON%" --no-install-project"
if !errorlevel! neq 0 (
    echo [ERROR] Dependency install failed for .venv-py314t
    del /Q "%PROJECT_ROOT%\uv.lock" 2>nul
    pause
    exit /b 1
)
:: After sync, regenerate lockfile to keep it up-to-date
cmd /c "set VIRTUAL_ENV=%VENV_314%&& uv lock --python "%VENV_PYTHON%""
copy /Y "%PROJECT_ROOT%\uv.lock" "%LOCK_314%" >nul
echo [OK] Updated %LOCK_314%
del /Q "%PROJECT_ROOT%\uv.lock" 2>nul
echo [OK] .venv-py314t ready.
echo.

:done
echo ========================================
echo All done!
echo   Activate: .venv-py314t\Scripts\activate
echo ========================================
pause
exit /b 0