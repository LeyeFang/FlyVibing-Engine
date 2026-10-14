@echo off
REM Link the user & developer toolchain repo into the ExtDev folder under Utils
REM so the engine's tests and docs can keep using the historical paths.
REM
REM Single source of truth stays in FlyVibing-User-And-Developer-Utils; this
REM directory is gitignored (junction contents are never committed here).
REM
REM Usage:  Utils\Dev\link_tools.bat [path-to-tools-repo]
REM         (or set FLYVIBING_UTILS_DIR to the tools repo root)

setlocal
set "TOOLS=%~1"
if "%TOOLS%"=="" set "TOOLS=%FLYVIBING_UTILS_DIR%"
if "%TOOLS%"=="" set "TOOLS=%~dp0..\..\..\FlyVibing-User-And-Developer-Utils"

if not exist "%TOOLS%\packages\editor-mcp" (
    echo [link_tools] tools repo not found: %TOOLS%
    echo [link_tools] clone https://github.com/LeyeFang/FlyVibing-User-And-Developer-Utils
    echo [link_tools] or pass the path:  link_tools.bat D:\path\to\FlyVibing-User-And-Developer-Utils
    exit /b 1
)

set "DEST=%~dp0..\ExtDev"
if not exist "%DEST%" mkdir "%DEST%"

call :link "EditorMcp"    "%TOOLS%\packages\editor-mcp"
call :link "NodeEditor"   "%TOOLS%\packages\node-editor\src\flyvibing_node_editor"
call :link "ExtensionKit" "%TOOLS%\packages\extension-kit\src\flyvibing_extension_kit"

echo [link_tools] done. tools repo = %TOOLS%
echo [link_tools] tip: set FLYVIBING_UTILS_DIR=%TOOLS% so tools can find the repo.
exit /b 0

:link
if exist "%DEST%\%~1" (
    echo [link_tools] skip %~1 (already exists)
    exit /b 0
)
cmd /c mklink /J "%DEST%\%~1" "%~2" >nul
if errorlevel 1 (echo [link_tools] FAILED: %~1) else (echo [link_tools] linked %~1)
exit /b 0
