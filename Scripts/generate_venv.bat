@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: 获取脚本所在目录（Scripts）和项目根目录
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..

:: 定义虚拟环境路径
set VENV_312=%PROJECT_ROOT%\.venv-py312
set VENV_314=%PROJECT_ROOT%\.venv-py314t

:: 锁文件路径
set LOCK_312=%SCRIPT_DIR%\uv-py312.lock
set LOCK_314=%SCRIPT_DIR%\uv-py314t.lock

:: 切换到项目根目录
cd /d "%PROJECT_ROOT%" || (echo 错误：无法进入项目目录 & pause & exit /b 1)

:: 检查 uv 是否安装
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo 错误：未找到 uv，请先安装 uv (https://docs.astral.sh/uv/getting-started/installation/)
    pause
    exit /b 1
)

:: 检查锁文件是否存在
if not exist "%LOCK_312%" (
    echo 错误：找不到锁文件 %LOCK_312%，请确保仓库包含该文件。
    pause
    exit /b 1
)
if not exist "%LOCK_314%" (
    echo 错误：找不到锁文件 %LOCK_314%，请确保仓库包含该文件。
    pause
    exit /b 1
)

echo ========================================
echo 初始化 Python 3.12 环境
echo ========================================

:: 创建 3.12 虚拟环境（如果不存在）
if not exist "%VENV_312%\Scripts\activate.bat" (
    echo 创建虚拟环境 .venv-py312 ...
    uv venv --python 3.12 "%VENV_312%"
    if !errorlevel! neq 0 (
        echo 错误：创建虚拟环境失败，请检查 Python 3.12 是否已安装（可用 uv python install 3.12）
        pause
        exit /b 1
    )
) else (
    echo 虚拟环境已存在，跳过创建。
)

:: 临时复制锁文件到根目录
copy /Y "%LOCK_312%" "%PROJECT_ROOT%\uv.lock" >nul

:: 激活环境并同步依赖
echo 正在安装依赖（这可能需要几分钟）...
cmd /c "call "%VENV_312%\Scripts\activate.bat" && uv sync --locked"
if !errorlevel! neq 0 (
    echo 错误：依赖安装失败
    del /Q "%PROJECT_ROOT%\uv.lock" 2>nul
    pause
    exit /b 1
)

:: 删除临时锁文件
del /Q "%PROJECT_ROOT%\uv.lock" 2>nul
echo [成功] Python 3.12 环境已就绪

echo.
echo ========================================
echo 初始化 Python 3.14t 环境
echo ========================================

:: 创建 3.14t 虚拟环境（如果不存在）
if not exist "%VENV_314%\Scripts\activate.bat" (
    echo 创建虚拟环境 .venv-py314t ...
    uv venv --python 3.14t "%VENV_314%"
    if !errorlevel! neq 0 (
        echo 错误：创建虚拟环境失败，请检查 Python 3.14t 是否已安装（可用 uv python install 3.14t）
        pause
        exit /b 1
    )
) else (
    echo 虚拟环境已存在，跳过创建。
)

:: 临时复制锁文件到根目录
copy /Y "%LOCK_314%" "%PROJECT_ROOT%\uv.lock" >nul

:: 激活环境并同步依赖
echo 正在安装依赖（这可能需要几分钟）...
cmd /c "call "%VENV_314%\Scripts\activate.bat" && uv sync --locked"
if !errorlevel! neq 0 (
    echo 错误：依赖安装失败
    del /Q "%PROJECT_ROOT%\uv.lock" 2>nul
    pause
    exit /b 1
)

del /Q "%PROJECT_ROOT%\uv.lock" 2>nul
echo [成功] Python 3.14t 环境已就绪

echo.
echo ========================================
echo 全部完成！
echo 使用方法：
echo   .venv-py312\Scripts\activate     # 激活 3.12 环境
echo   .venv-py314t\Scripts\activate    # 激活 3.14t 环境
echo ========================================
pause
exit /b 0