@echo off
setlocal enabledelayedexpansion

:: Get script directory (Scripts) and project root
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..

:: Virtual environment paths
set VENV_312=%PROJECT_ROOT%\.venv-py312
set VENV_314=%PROJECT_ROOT%\.venv-py314t

:: Navigate to project root
cd /d "%PROJECT_ROOT%" || (echo [ERROR] Cannot enter project directory & pause & exit /b 1)

:: Check if uv is installed
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] uv not found. Please install uv first.
    pause
    exit /b 1
)

:: ------------------------------------------------------------
:: Python 3.12: sync deps (with gui group) + generate lock file
:: ------------------------------------------------------------
echo ========================================
echo Processing Python 3.12 environment
echo ========================================
if exist "%VENV_312%\Scripts\activate.bat" (
    echo Updating environment and generating lock file...
    cmd /c "call "%VENV_312%\Scripts\activate.bat" && uv sync --extra gui --active && uv lock"
    if !errorlevel! equ 0 (
        if exist "%PROJECT_ROOT%\uv.lock" (
            copy /Y "%PROJECT_ROOT%\uv.lock" "%SCRIPT_DIR%\uv-py312.lock"
            echo [OK] Saved uv-py312.lock to %SCRIPT_DIR%
            del /Q "%PROJECT_ROOT%\uv.lock"
            echo [OK] Deleted uv.lock from project root
        ) else (
            echo [WARN] uv.lock was not generated, please check
        )
    ) else (
        echo [FAIL] uv sync / lock failed. Check network or dependencies.
    )
) else (
    echo [ERROR] Virtual environment not found: %VENV_312%
)

echo.
:: ------------------------------------------------------------
:: Python 3.14t: sync deps (with gui-314, build from source) + generate lock file
:: ------------------------------------------------------------
echo ========================================
echo Processing Python 3.14t environment
echo ========================================
:: imgui-bundle (gui-314) needs MSVC to build from source
call :FindMSVC
if exist "%VENV_314%\Scripts\activate.bat" (
    echo Updating environment and generating lock file...
    cmd /c "call "%VENV_314%\Scripts\activate.bat" && uv sync --extra device --extra gui-314 --active && uv lock"
    if !errorlevel! equ 0 (
        if exist "%PROJECT_ROOT%\uv.lock" (
            copy /Y "%PROJECT_ROOT%\uv.lock" "%SCRIPT_DIR%\uv-py314t.lock"
            echo [OK] Saved uv-py314t.lock to %SCRIPT_DIR%
            del /Q "%PROJECT_ROOT%\uv.lock"
            echo [OK] Deleted uv.lock from project root
        ) else (
            echo [WARN] uv.lock was not generated, please check
        )
    ) else (
        echo [FAIL] uv sync / lock failed. Check network or dependencies.
    )
) else (
    echo [ERROR] Virtual environment not found: %VENV_314%
)

echo.
echo All done. Press any key to exit...
pause >nul
exit /b 0


:: ============================================================
:: :FindMSVC - Auto-detect Visual Studio and load MSVC environment
:: Search order: vswhere -> common install paths
:: ============================================================
:FindMSVC
where cl >nul 2>nul
if %errorlevel% equ 0 (
    echo [MSVC] cl.exe already in PATH, skipping detection
    exit /b 0
)

set "VSWHERE_PATH=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE_PATH%" set "VSWHERE_PATH=%ProgramFiles%\Microsoft Visual Studio\Installer\vswhere.exe"

if exist "%VSWHERE_PATH%" (
    echo [MSVC] Searching for Visual Studio via vswhere...
    for /f "usebackq tokens=*" %%i in (`"%VSWHERE_PATH%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set VSINST=%%i
    if defined VSINST (
        set "VCVARS=%VSINST%\VC\Auxiliary\Build\vcvarsall.bat"
        if exist "!VCVARS!" (
            echo [MSVC] Found: !VCVARS!
            call "!VCVARS!" x64
            if !errorlevel! equ 0 (
                echo [MSVC] Environment loaded successfully
                exit /b 0
            )
        )
    )
) else (
    echo [MSVC] vswhere not found, trying common paths...
)

:: Fallback: iterate over common install paths
for %%p in (
    "%ProgramFiles%\Microsoft Visual Studio\2022\Community"
    "%ProgramFiles%\Microsoft Visual Studio\2022\Professional"
    "%ProgramFiles%\Microsoft Visual Studio\2022\Enterprise"
    "%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools"
    "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Community"
    "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Professional"
    "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Enterprise"
    "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools"
    "%ProgramFiles%\Microsoft Visual Studio\2019\Community"
    "%ProgramFiles%\Microsoft Visual Studio\2019\Professional"
    "%ProgramFiles%\Microsoft Visual Studio\2019\Enterprise"
    "%ProgramFiles%\Microsoft Visual Studio\2019\BuildTools"
) do (
    if exist "%%p\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [MSVC] Found: %%p\VC\Auxiliary\Build\vcvarsall.bat
        call "%%p\VC\Auxiliary\Build\vcvarsall.bat" x64
        if !errorlevel! equ 0 (
            echo [MSVC] Environment loaded successfully
            exit /b 0
        )
    )
)

echo [WARN] MSVC compiler not found! imgui-bundle build may fail.
echo        Please install "Desktop development with C++" workload.
exit /b 0