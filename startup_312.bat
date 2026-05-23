@echo off
echo Activating Python 3.12 environment...
call .venv-py312\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo Error: failed to activate .venv-py312, please run Scripts\setup.bat first
    pause
    exit /b %errorlevel%
)
echo Running EntryPoint.py...
python EntryPoint.py
pause