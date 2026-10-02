@echo off
setlocal

:: ============================================
:: Utils/User/player.bat — 无编辑器运行项目（PlayerEntry）
:: 解释器选择:
::   1) 引擎目录内置运行时 3.14t : Resource\runtime\python3.14t.exe
::      (runtime 镜像内含 GIL 版 python.exe — 不可用, 易踩坑)
::   2) 开发 venv               : .venv-py314t\Scripts\python.exe
:: 用法:
::   Utils\User\player.bat <game.json|.myproj|.scene> [--dry-run] [--frames N] [--verbose]
:: 示例:
::   Utils\User\player.bat Test\TestProject\EmptyGame\EmptyGame.myproj --dry-run
::   Utils\User\player.bat Test\TestProject\EmptyGame\EmptyGame.myproj --frames 120
:: ============================================

:: 回到引擎根目录（builtin 资源相对解析依赖工作目录）
cd /d "%~dp0..\.."

set "RUNTIME_PY=%~dp0..\..\Resource\runtime\python3.14t.exe"
set "VENV_PY=%~dp0..\..\.venv-py314t\Scripts\python.exe"

set "PYTHON="
if exist "%RUNTIME_PY%" set "PYTHON=%RUNTIME_PY%"
if not defined PYTHON if exist "%VENV_PY%" set "PYTHON=%VENV_PY%"

if not defined PYTHON (
    echo [ERROR] No Python runtime found.
    echo   Installed build expects: Resource\runtime\python3.14t.exe
    echo   Dev build expects:      .venv-py314t\Scripts\python.exe
    echo   Dev setup: run Utils\Dev\setup_env.bat
    pause
    exit /b 1
)

set "PYTHONNOUSERSITE=1"

"%PYTHON%" -Xgil=0 "%~dp0..\..\Application\PlayerEntry.py" %*

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Player exited with code %errorlevel%
    pause
)

endlocal
