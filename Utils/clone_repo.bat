@echo off
chcp 65001 >nul
title 克隆 MyGameEngine-Python

echo ============================================
echo    MyGameEngine-Python 一键克隆脚本
echo ============================================
echo.
echo 注意: GitHub 已不支持密码登录，请使用 Personal Access Token。
echo 如果没有 Token，请先去 GitHub 生成:
echo   Settings ^> Developer settings ^> Personal access tokens ^> Tokens (classic)
echo   勾选 "repo" 权限后生成，然后复制到这里使用。
echo.

set /p GIT_USER="请输入 GitHub 用户名: "
set /p GIT_TOKEN="请输入 GitHub Personal Access Token: "

set REPO_URL=https://%GIT_USER%:%GIT_TOKEN%@github.com/LeyeFang/MyGameEngine-Python.git

echo.
echo 正在克隆项目到当前目录...
echo.

git clone %REPO_URL%

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================
    echo   克隆成功！
    echo   项目目录: %CD%\MyGameEngine-Python
    echo ============================================
) else (
    echo.
    echo ============================================
    echo   克隆失败，请检查用户名和 Token 是否正确。
    echo ============================================
)

echo.
pause
