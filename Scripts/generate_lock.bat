@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: 获取脚本所在目录（Scripts）和项目根目录
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..

:: 定义虚拟环境路径
set VENV_312=%PROJECT_ROOT%\.venv-py312
set VENV_314=%PROJECT_ROOT%\.venv-py314t

:: 切换到项目根目录
cd /d "%PROJECT_ROOT%" || (echo 错误：无法进入项目目录 & pause & exit /b 1)

echo ========================================
echo 开始生成 Python 3.12 环境的锁文件
echo ========================================
if exist "%VENV_312%\Scripts\activate.bat" (
    cmd /c "call "%VENV_312%\Scripts\activate.bat" && uv lock"
    if !errorlevel! equ 0 (
        copy /Y "%PROJECT_ROOT%\uv.lock" "%SCRIPT_DIR%\uv-py312.lock"
        echo [成功] 已保存 uv-py312.lock 到 %SCRIPT_DIR%
        del /Q "%PROJECT_ROOT%\uv.lock"
        echo [清理] 已删除根目录下的 uv.lock
    ) else (
        echo [失败] uv lock 命令出错，请检查网络或依赖。
    )
) else (
    echo [错误] 找不到虚拟环境：%VENV_312%
)

echo.
echo ========================================
echo 开始生成 Python 3.14t 环境的锁文件
echo ========================================
if exist "%VENV_314%\Scripts\activate.bat" (
    cmd /c "call "%VENV_314%\Scripts\activate.bat" && uv lock"
    if !errorlevel! equ 0 (
        copy /Y "%PROJECT_ROOT%\uv.lock" "%SCRIPT_DIR%\uv-py314t.lock"
        echo [成功] 已保存 uv-py314t.lock 到 %SCRIPT_DIR%
        del /Q "%PROJECT_ROOT%\uv.lock"
        echo [清理] 已删除根目录下的 uv.lock
    ) else (
        echo [失败] uv lock 命令出错，请检查网络或依赖。
    )
) else (
    echo [错误] 找不到虚拟环境：%VENV_314%
)

echo.
echo 全部完成。按任意键退出...
pause >nul
exit /b 0