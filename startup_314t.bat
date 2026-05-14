@echo off
echo 正在激活 Python 3.14t 环境...
call .venv-py314t\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo 错误：无法激活 .venv-py314t 环境，请先运行 Scripts\setup.bat
    pause
    exit /b %errorlevel%
)
echo 运行 EntryPoint.py...
python EntryPoint.py
pause