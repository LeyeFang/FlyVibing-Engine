@echo off
echo Activating Python 3.14t environment...
call .venv-py314t\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo Error: failed to activate .venv-py314t, please run Scripts\setup.bat first
    pause
    exit /b %errorlevel%
)
echo Running Application\EntryPoint.py...
python -Xgil=0 Application\EntryPoint.py
pause