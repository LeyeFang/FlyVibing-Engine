@echo off
setlocal enabledelayedexpansion

:: ============================================================
:: Utils/Dev/rebuild_lock.bat — 维护者专用
::   依赖变更后重生成 Utils/Dev/uv-py314t.lock（可复现同步的基准）
::   流程: 注入 imgui 引导轮 → uv sync(按 pyproject 解析) → uv lock → 收起锁文件
:: 前置: 已完成 Utils/Dev/setup_env.bat（venv 存在）; uv 已装
:: 注意: 若 Resource/wheels 的 imgui 引导轮缺失, 将回退 git 源码构建
::       （需要 git / CMake 3.26.1+ / MSVC C++）
:: ============================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%..\.." || (echo [ERROR] cannot locate repo root & pause & exit /b 1)
set "ROOT=%CD%"
set "VENV=%ROOT%\.venv-py314t"
set "VENV_PY=%VENV%\Scripts\python.exe"
set "LOCK=%SCRIPT_DIR%uv-py314t.lock"
set "IMGUI_WHEEL=%ROOT%\Resource\wheels\imgui_bundle-1.92.5-cp314-cp314t-win_amd64.whl"

where uv >nul 2>nul || (echo [ERROR] uv not found & pause & exit /b 1)
if not exist "%VENV_PY%" (echo [ERROR] run Utils\Dev\setup_env.bat first & pause & exit /b 1)

if not exist "%IMGUI_WHEEL%" (
    echo [WARN] imgui bootstrap wheel missing — uv will build from git source:
    where git >nul 2>nul || echo   [MISSING] git
    where cmake >nul 2>nul || echo   [MISSING] CMake ^>= 3.26.1
    where cl >nul 2>nul || echo   [INFO] MSVC not in PATH (elsewhere detected via vswhere)
) else (
    echo [1/3] injecting imgui-bundle bootstrap wheel ...
    uv pip install --python "%VENV_PY%" --reinstall "%IMGUI_WHEEL%"
    if errorlevel 1 (echo [ERROR] wheel inject failed & pause & exit /b 1)
)

echo [2/3] uv sync --extra device (resolve from pyproject) ...
cmd /c "set VIRTUAL_ENV=%VENV%&& uv sync --python "%VENV_PY%" --no-install-project --extra device"
if errorlevel 1 (echo [ERROR] uv sync failed & pause & exit /b 1)

echo [3/3] uv lock + harvest ...
cmd /c "set VIRTUAL_ENV=%VENV%&& uv lock --python "%VENV_PY%""
if errorlevel 1 (echo [ERROR] uv lock failed & pause & exit /b 1)
if not exist "%ROOT%\uv.lock" (echo [ERROR] uv.lock not generated & pause & exit /b 1)
copy /Y "%ROOT%\uv.lock" "%LOCK%" >nul
del /Q "%ROOT%\uv.lock" 2>nul
echo [OK] updated %LOCK%
pause
