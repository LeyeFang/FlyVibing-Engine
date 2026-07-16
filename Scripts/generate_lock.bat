@echo off
setlocal enabledelayedexpansion

:: Get script directory (Scripts) and project root (resolved to absolute path)
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%.." || (echo [ERROR] Cannot enter project directory & pause & exit /b 1)
set PROJECT_ROOT=%CD%
cd /d "%SCRIPT_DIR%"

:: Virtual environment paths
set VENV_314=%PROJECT_ROOT%\.venv-py314t

:: Navigate to project root
cd /d "%PROJECT_ROOT%"

:: Check if uv is installed
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] uv not found. Please install uv first.
    echo   Download: https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)


:: ============================================================
:: Pre-flight toolchain check (git, CMake, MSVC)
:: imgui-bundle builds from source and needs all three
:: ============================================================
call :PreFlightCheck


:: ------------------------------------------------------------
:: Python 3.14t: sync deps + generate lock file
:: ------------------------------------------------------------
echo ========================================
echo Processing Python 3.14t environment
echo ========================================

call :FindMSVC
if exist "%VENV_314%\Scripts\activate.bat" (
    echo Updating environment and generating lock file...
    cmd /c "call "%VENV_314%\Scripts\activate.bat" && uv sync --no-install-project --extra device --extra gui-314 --active && uv lock"
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
:: :PreFlightCheck - Check all toolchain prerequisites
:: Calls CheckGit, CheckCMake, FindMSVC; prints summary
:: ============================================================
:PreFlightCheck
echo ========================================
echo   Pre-flight Toolchain Check
echo ========================================
echo.

set TOOLCHAIN_OK=1

call :CheckGit
call :CheckCMake
call :CheckMSVCDetect

echo.
if !TOOLCHAIN_OK! equ 1 (
    echo [OK] All toolchain checks passed.
) else (
    echo ============================================
    echo [WARN] Some tools are missing!
    echo.
    echo The imgui-bundle package will be built from source.
    echo It requires:
    echo   - git       ^(to clone the source^)
    echo   - CMake     ^(build system, v3.26.1+^)
    echo   - MSVC C++  ^(compiler^)
    echo.
    echo See the messages above for install instructions.
    echo ============================================
    echo.
    timeout /t 3 /nobreak >nul
)
echo ========================================
echo.
exit /b 0


:: ============================================================
:: :CheckGit - Verify git is installed and accessible
:: ============================================================
:CheckGit
where git >nul 2>nul
if %errorlevel% equ 0 (
    for /f "tokens=3" %%v in ('git --version 2^>nul') do (
        echo [OK] git found: %%v
    )
    exit /b 0
)
echo [MISSING] git
echo   -^> Download: https://git-scm.com/download/win
echo   -^> Install with default options ("Git from the command line")
echo.
set TOOLCHAIN_OK=0
exit /b 0


:: ============================================================
:: :CheckCMake - Verify CMake >= 3.26.1 is installed
:: ============================================================
:CheckCMake
where cmake >nul 2>nul
if %errorlevel% neq 0 (
    echo [MISSING] CMake
    echo   -^> Download: https://cmake.org/download/
    echo   -^> Install the Windows x64 Installer.
    echo   -^> IMPORTANT: Check "Add CMake to system PATH" during install.
    echo.
    set TOOLCHAIN_OK=0
    exit /b 0
)

:: Extract version: "cmake version X.Y.Z" -> take 3rd token of 1st line only
set "CMAKE_VER=unknown"
for /f "tokens=3" %%v in ('cmake --version 2^>nul') do if "!CMAKE_VER!"=="unknown" set "CMAKE_VER=%%v"

echo [OK] CMake found: !CMAKE_VER! (requires ^>= 3.26.1^)
exit /b 0


:: ============================================================
:: :CheckMSVCDetect - Check MSVC availability (detect only, no env load)
:: ============================================================
:CheckMSVCDetect
where cl >nul 2>nul
if %errorlevel% equ 0 (
    echo [OK] MSVC compiler ^(cl.exe^) found in PATH
    exit /b 0
)

set "VSWHERE_PATH=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE_PATH%" set "VSWHERE_PATH=%ProgramFiles%\Microsoft Visual Studio\Installer\vswhere.exe"

if exist "%VSWHERE_PATH%" (
    for /f "usebackq tokens=*" %%i in (`"%VSWHERE_PATH%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2^>nul`) do (
        echo [OK] MSVC found via vswhere: %%i
        exit /b 0
    )
)

:: Fallback: scan common paths
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
        echo [OK] MSVC found: %%p
        exit /b 0
    )
)

:: Wildcard scan: non-standard version folders (e.g. "18", preview builds)
for /d %%v in ("%ProgramFiles(x86)%\Microsoft Visual Studio\*") do (
    if exist "%%v\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [OK] MSVC found: %%v\BuildTools
        exit /b 0
    )
    if exist "%%v\Community\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [OK] MSVC found: %%v\Community
        exit /b 0
    )
    if exist "%%v\Professional\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [OK] MSVC found: %%v\Professional
        exit /b 0
    )
    if exist "%%v\Enterprise\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [OK] MSVC found: %%v\Enterprise
        exit /b 0
    )
)
for /d %%v in ("%ProgramFiles%\Microsoft Visual Studio\*") do (
    if exist "%%v\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [OK] MSVC found: %%v\BuildTools
        exit /b 0
    )
    if exist "%%v\Community\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [OK] MSVC found: %%v\Community
        exit /b 0
    )
    if exist "%%v\Professional\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [OK] MSVC found: %%v\Professional
        exit /b 0
    )
    if exist "%%v\Enterprise\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [OK] MSVC found: %%v\Enterprise
        exit /b 0
    )
)

echo [MISSING] MSVC C++ compiler
echo   -^> Option A ^(lightweight^): Visual Studio Build Tools 2022
echo     https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022
echo     Select "Desktop development with C++" workload ^(~2.5 GB^)
echo   -^> Option B ^(full IDE^): Visual Studio 2022 Community ^(free^)
echo     https://visualstudio.microsoft.com/zh-cn/downloads/
echo     Select "Desktop development with C++" workload ^(~4-6 GB^)
echo.
set TOOLCHAIN_OK=0
exit /b 0


:: ============================================================
:: :FindMSVC - Auto-detect Visual Studio and load MSVC environment
:: Search order: vswhere -> common install paths -> wildcard
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

:: Wildcard scan: non-standard version folders (e.g. "18", preview builds)
for /d %%v in ("%ProgramFiles(x86)%\Microsoft Visual Studio\*") do (
    if exist "%%v\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [MSVC] Found: %%v\BuildTools\VC\Auxiliary\Build\vcvarsall.bat
        call "%%v\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
        if !errorlevel! equ 0 (
            echo [MSVC] Environment loaded successfully
            exit /b 0
        )
    )
    if exist "%%v\Community\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [MSVC] Found: %%v\Community\VC\Auxiliary\Build\vcvarsall.bat
        call "%%v\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
        if !errorlevel! equ 0 (
            echo [MSVC] Environment loaded successfully
            exit /b 0
        )
    )
    if exist "%%v\Professional\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [MSVC] Found: %%v\Professional\VC\Auxiliary\Build\vcvarsall.bat
        call "%%v\Professional\VC\Auxiliary\Build\vcvarsall.bat" x64
        if !errorlevel! equ 0 (
            echo [MSVC] Environment loaded successfully
            exit /b 0
        )
    )
    if exist "%%v\Enterprise\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [MSVC] Found: %%v\Enterprise\VC\Auxiliary\Build\vcvarsall.bat
        call "%%v\Enterprise\VC\Auxiliary\Build\vcvarsall.bat" x64
        if !errorlevel! equ 0 (
            echo [MSVC] Environment loaded successfully
            exit /b 0
        )
    )
)
for /d %%v in ("%ProgramFiles%\Microsoft Visual Studio\*") do (
    if exist "%%v\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [MSVC] Found: %%v\BuildTools\VC\Auxiliary\Build\vcvarsall.bat
        call "%%v\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
        if !errorlevel! equ 0 (
            echo [MSVC] Environment loaded successfully
            exit /b 0
        )
    )
    if exist "%%v\Community\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [MSVC] Found: %%v\Community\VC\Auxiliary\Build\vcvarsall.bat
        call "%%v\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
        if !errorlevel! equ 0 (
            echo [MSVC] Environment loaded successfully
            exit /b 0
        )
    )
    if exist "%%v\Professional\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [MSVC] Found: %%v\Professional\VC\Auxiliary\Build\vcvarsall.bat
        call "%%v\Professional\VC\Auxiliary\Build\vcvarsall.bat" x64
        if !errorlevel! equ 0 (
            echo [MSVC] Environment loaded successfully
            exit /b 0
        )
    )
    if exist "%%v\Enterprise\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [MSVC] Found: %%v\Enterprise\VC\Auxiliary\Build\vcvarsall.bat
        call "%%v\Enterprise\VC\Auxiliary\Build\vcvarsall.bat" x64
        if !errorlevel! equ 0 (
            echo [MSVC] Environment loaded successfully
            exit /b 0
        )
    )
)

echo.
echo ============================================
echo [WARN]  MSVC C++ compiler NOT FOUND!
echo ============================================
echo.
echo imgui-bundle needs a C++ compiler to build from source.
echo.
echo Choose one of the following:
echo.
echo   [Lightweight - recommended] Visual Studio Build Tools 2022
echo     Download: https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022
echo     Run the installer, select "Desktop development with C++" workload.
echo     Estimated download: ~2.5 GB
echo.
echo   [Full IDE - free] Visual Studio 2022 Community
echo     Download: https://visualstudio.microsoft.com/zh-cn/downloads/
echo     Run the installer, select "Desktop development with C++" workload.
echo     Estimated download: ~4-6 GB
echo.
echo After installation, re-run this script.
echo ============================================
exit /b 0