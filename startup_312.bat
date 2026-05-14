@echo off
echo 正在激活 Python 3.12 环境...
call .venv-py312\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo 错误：无法激活 .venv-py312 环境，请先运行 Scripts\setup.bat
    pause
    exit /b %errorlevel%
)
echo 运行 EntryPoint.py...
python EntryPoint.py
pause