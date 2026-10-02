@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

echo ============================================
echo   Node Graph Editor MCP - One-Click Install
echo ============================================
echo.

:: -- 1. Project root --
set "PROJECT_DIR=%~dp0..\..\.."
pushd "%PROJECT_DIR%" 2>nul || (
    echo [ERROR] Cannot locate project root
    pause & exit /b 1
)
set "PROJECT_DIR=%CD%"
popd

echo [1/4] Project dir: %PROJECT_DIR%

:: -- 2. Install mcp packages --
echo [2/4] Installing MCP Python package...

:: Detect venv Python (only .venv-py314t is the canonical venv)
if exist "%PROJECT_DIR%\.venv-py314t\Scripts\python.exe" (
    set "PYTHON=%PROJECT_DIR%\.venv-py314t\Scripts\python.exe"
) else (
    echo [ERROR] Virtual environment not found: .venv-py314t\
    echo Please run Utils\Dev\setup_env.bat first.
    pause & exit /b 1
)

echo   Using: %PYTHON%

:: Step 2: install mcp via uv (reproducible, respects lockfile constraints)
echo   Step 2: uv pip install mcp...
uv pip install --python "%PYTHON%" mcp
if %ERRORLEVEL% NEQ 0 (
    echo   [WARNING] 'mcp' install failed, trying 'fastmcp'...
    uv pip install --python "%PYTHON%" fastmcp
    if %ERRORLEVEL% NEQ 0 (
        echo   [WARNING] Both 'mcp' and 'fastmcp' install failed.
        echo   You can install manually: uv pip install --python "%PYTHON%" mcp
        echo   Continuing anyway...
    )
)

:: -- 3. Generate MCP config --
echo [3/4] Generating MCP config...

set "WORKSPACE_MCP=%PROJECT_DIR%\.vscode\mcp.json"

if not exist "%PROJECT_DIR%\.vscode" mkdir "%PROJECT_DIR%\.vscode"

if exist "%WORKSPACE_MCP%" (
    echo   Existing config found, merging...
    %PYTHON% -c "import json, sys; d=json.load(open(sys.argv[1],'r',encoding='utf-8')); d.setdefault('servers',{}); d['servers']['node-graph-editor']={'type':'stdio','command':sys.argv[3],'args':[sys.argv[4],sys.argv[5]],'cwd':sys.argv[2]}; json.dump(d,open(sys.argv[1],'w',encoding='utf-8'),indent=2,ensure_ascii=False); print('OK')" "%WORKSPACE_MCP%" "%PROJECT_DIR%" "%PYTHON%" "-m" "Utils.User.NodeEditor.mcp_server"
) else (
    %PYTHON% -c "import json, sys; d={'servers':{'node-graph-editor':{'type':'stdio','command':sys.argv[2],'args':[sys.argv[3],sys.argv[4]],'cwd':sys.argv[1]}}}; json.dump(d,open(sys.argv[5],'w',encoding='utf-8'),indent=2,ensure_ascii=False); print('OK')" "%PROJECT_DIR%" "%PYTHON%" "-m" "Utils.User.NodeEditor.mcp_server" "%WORKSPACE_MCP%"
)

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to generate MCP config
    pause & exit /b 1
)

:: -- 4. Verify --
echo [4/4] Verifying...

if exist "%PROJECT_DIR%\Utils\User\NodeEditor\mcp_server.py" (
    echo   [OK] mcp_server.py found
) else (
    echo   [ERROR] mcp_server.py not found
    pause & exit /b 1
)

%PYTHON% -c "import mcp; print('  [OK] mcp package importable')" 2>nul || (
    %PYTHON% -c "import fastmcp; print('  [OK] fastmcp package importable')" 2>nul || (
        echo   [WARN] mcp/fastmcp not importable - MCP server needs manual start
    )
)

echo   [OK] Verification complete

echo.
echo ============================================
echo   Install complete!
echo.
echo   Restart VS Code, then use in Copilot Chat.
echo.
echo   Config: %WORKSPACE_MCP%
echo ============================================
pause
