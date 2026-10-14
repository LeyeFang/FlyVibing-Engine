@echo off
setlocal enabledelayedexpansion

:: ============================================================
:: FlyVibingEngine — 开发者一键环境脚本 (Utils/Dev/setup_env.bat)
::   新机器引导 / 日常修复 / 依赖更新 三合一
::
:: 前置: uv (https://docs.astral.sh/uv/) — 其余自动
:: 说明:
::   - Python 3.14t (free-threaded) 由 uv 托管（缺失时自动安装）
::   - 依赖按 Utils/Dev/uv-py314t.lock 同步（可复现）
::   - imgui-bundle 是 git 依赖（PyPI 无 cp314t 发行, 无法自动下载）——
::     由 Resource/wheels 内的自建引导轮注入（该单轮随 git 仓库提供）
:: ============================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%..\.." || (echo [ERROR] cannot locate repo root & pause & exit /b 1)
set "ROOT=%CD%"
set "VENV=%ROOT%\.venv-py314t"
set "VENV_PY=%VENV%\Scripts\python.exe"
set "LOCK=%SCRIPT_DIR%uv-py314t.lock"
set "WHEELS=%ROOT%\Resource\wheels"
set "IMGUI_WHEEL=%WHEELS%\imgui_bundle-1.92.5-cp314-cp314t-win_amd64.whl"

echo ============================================
echo   FlyVibingEngine - Dev Environment Setup
echo   root: %ROOT%
echo ============================================

:: [1/5] uv
where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv not found. Install: https://docs.astral.sh/uv/
    pause
    exit /b 1
)
echo [1/5] uv OK

:: [2/5] Python 3.14t (idempotent)
uv python install 3.14t >nul
if errorlevel 1 (
    echo [ERROR] 'uv python install 3.14t' failed
    pause
    exit /b 1
)
echo [2/5] Python 3.14t OK

:: [3/5] venv
if not exist "%VENV_PY%" (
    echo [3/5] creating .venv-py314t ...
    uv venv --python 3.14t "%VENV%"
    if errorlevel 1 (echo [ERROR] uv venv failed & pause & exit /b 1)
) else (
    echo [3/5] .venv-py314t exists
)

:: [4/5] imgui bootstrap wheel (git 依赖的唯一可离线来源)
if not exist "%IMGUI_WHEEL%" (
    echo [WARN] bootstrap wheel missing: %IMGUI_WHEEL%
    echo        restore from git: git checkout -- Resource/wheels/
) else (
    echo [4/5] injecting imgui-bundle bootstrap wheel ...
    uv pip install --python "%VENV_PY%" --reinstall "%IMGUI_WHEEL%"
    if errorlevel 1 (echo [ERROR] wheel inject failed & pause & exit /b 1)
)

:: [5/5] sync from lock (PyPI 拉取其余依赖)
if not exist "%LOCK%" (
    echo [ERROR] lock missing: %LOCK%
    pause
    exit /b 1
)
copy /Y "%LOCK%" "%ROOT%\uv.lock" >nul
echo [5/5] uv sync (may take a few minutes) ...
cmd /c "set VIRTUAL_ENV=%VENV%&& uv sync --python "%VENV_PY%" --no-install-project --extra device"
set "SYNC_RC=%errorlevel%"
del /Q "%ROOT%\uv.lock" 2>nul
if not "%SYNC_RC%"=="0" (
    echo [ERROR] uv sync failed — check network / lock file
    pause
    exit /b 1
)

:: verify
"%VENV_PY%" -c "import glfw, OpenGL, numpy, imgui_bundle, mcp; print('[OK] core imports')"
if errorlevel 1 (echo [WARN] import check failed & pause & exit /b 1)

echo ============================================
echo  DONE: .venv-py314t ready
echo    editor: startup.bat
echo    player: Utils\User\player.bat
echo ============================================
pause
