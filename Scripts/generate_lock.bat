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

:: 检查 uv 是否安装
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo 错误：未找到 uv，请先安装 uv
    pause
    exit /b 1
)

:: ------------------------------------------------------------
:: Python 3.12 环境：同步依赖（包含 gui 组） + 生成锁文件
:: ------------------------------------------------------------
echo ========================================
echo 处理 Python 3.12 环境
echo ========================================
if exist "%VENV_312%\Scripts\activate.bat" (
    echo 正在更新环境并生成锁文件...
    cmd /c "call "%VENV_312%\Scripts\activate.bat" && uv sync --extra gui --active && uv lock"
    if !errorlevel! equ 0 (
        if exist "%PROJECT_ROOT%\uv.lock" (
            copy /Y "%PROJECT_ROOT%\uv.lock" "%SCRIPT_DIR%\uv-py312.lock"
            echo [成功] 已保存 uv-py312.lock 到 %SCRIPT_DIR%
            del /Q "%PROJECT_ROOT%\uv.lock"
            echo [清理] 已删除根目录下的 uv.lock
        ) else (
            echo [警告] uv.lock 未生成，请检查
        )
    ) else (
        echo [失败] uv sync / lock 命令出错，请检查网络或依赖。
    )
) else (
    echo [错误] 找不到虚拟环境：%VENV_312%
)

echo.
:: ------------------------------------------------------------
:: Python 3.14t 环境：同步依赖（含 gui-314，从源码编译） + 生成锁文件
:: ------------------------------------------------------------
echo ========================================
echo 处理 Python 3.14t 环境
echo ========================================
:: imgui-bundle (gui-314) 需要从源码编译，先确保 MSVC 可用
call :FindMSVC
if exist "%VENV_314%\Scripts\activate.bat" (
    echo 正在更新环境并生成锁文件...
    cmd /c "call "%VENV_314%\Scripts\activate.bat" && uv sync --extra device --extra gui-314 --active && uv lock"
    if !errorlevel! equ 0 (
        if exist "%PROJECT_ROOT%\uv.lock" (
            copy /Y "%PROJECT_ROOT%\uv.lock" "%SCRIPT_DIR%\uv-py314t.lock"
            echo [成功] 已保存 uv-py314t.lock 到 %SCRIPT_DIR%
            del /Q "%PROJECT_ROOT%\uv.lock"
            echo [清理] 已删除根目录下的 uv.lock
        ) else (
            echo [警告] uv.lock 未生成，请检查
        )
    ) else (
        echo [失败] uv sync / lock 命令出错，请检查网络或依赖。
    )
) else (
    echo [错误] 找不到虚拟环境：%VENV_314%
)

echo.
echo 全部完成。按任意键退出...
pause >nul
exit /b 0


:: ============================================================
:: :FindMSVC - 自动检测 Visual Studio 并加载 MSVC 环境变量
:: 搜索顺序: vswhere → 常见安装路径
:: ============================================================
:FindMSVC
where cl >nul 2>nul
if %errorlevel% equ 0 (
    echo [MSVC] cl.exe 已在 PATH 中，跳过检测
    exit /b 0
)

set VSWHERE_PATH=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe
if not exist "%VSWHERE_PATH%" set VSWHERE_PATH=%ProgramFiles%\Microsoft Visual Studio\Installer\vswhere.exe

if exist "%VSWHERE_PATH%" (
    echo [MSVC] 正在通过 vswhere 查找 Visual Studio 安装...
    for /f "usebackq tokens=*" %%i in (`"%VSWHERE_PATH%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set VSINST=%%i
    if defined VSINST (
        set VCVARS="%VSINST%\VC\Auxiliary\Build\vcvarsall.bat"
        if exist !VCVARS! (
            echo [MSVC] 找到: !VCVARS!
            call !VCVARS! x64
            if !errorlevel! equ 0 (
                echo [MSVC] 环境加载成功
                exit /b 0
            )
        )
    )
) else (
    echo [MSVC] vswhere 未找到，尝试常见路径...
)

:: 备选：遍历常见安装路径
for %%p in (
    "%ProgramFiles%\Microsoft Visual Studio\2022\Community"
    "%ProgramFiles%\Microsoft Visual Studio\2022\Professional"
    "%ProgramFiles%\Microsoft Visual Studio\2022\Enterprise"
    "%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools"
    "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Community"
    "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Professional"
    "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Enterprise"
    "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools"
    "%ProgramFiles%\Microsoft Visual Studio\2019\Community"
    "%ProgramFiles%\Microsoft Visual Studio\2019\Professional"
    "%ProgramFiles%\Microsoft Visual Studio\2019\Enterprise"
    "%ProgramFiles%\Microsoft Visual Studio\2019\BuildTools"
) do (
    if exist "%%p\VC\Auxiliary\Build\vcvarsall.bat" (
        echo [MSVC] 找到: %%p\VC\Auxiliary\Build\vcvarsall.bat
        call "%%p\VC\Auxiliary\Build\vcvarsall.bat" x64
        if !errorlevel! equ 0 (
            echo [MSVC] 环境加载成功
            exit /b 0
        )
    )
)

echo [警告] 未找到 MSVC 编译器！编译 imgui-bundle 可能会失败
echo        请确保已安装 "使用 C++ 的桌面开发" 工作负载
exit /b 0