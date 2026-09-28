@echo off
setlocal

:: ============================================
:: PlayerEntry launcher (dev machine — uses dev venv, no editor)
:: 位置: Utils/Runtime/ —— 播放器专用脚本不放在引擎根（引擎根 = 开发编辑器）
:: Usage:
::   Utils\Runtime\player.bat <game.json|.myproj|.scene> [--dry-run] [--frames N] [--verbose]
:: Examples:
::   Utils\Runtime\player.bat Test\TestProject\EmptyGame\EmptyGame.myproj --dry-run
::   Utils\Runtime\player.bat Test\TestProject\EmptyGame\EmptyGame.myproj --frames 120
:: ============================================

:: 回到引擎根目录（builtin 资源相对解析依赖工作目录）
cd /d "%~dp0..\.."

set "VENV_PYTHON=%~dp0..\..\.venv-py314t\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Virtual environment not found: .venv-py314t\
    echo   Run Utils\generate_venv.bat first.
    pause
    exit /b 1
)

set "PYTHONNOUSERSITE=1"

"%VENV_PYTHON%" -Xgil=0 "%~dp0..\..\Application\PlayerEntry.py" %*

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Player exited with code %errorlevel%
    pause
)

endlocal
