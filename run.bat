@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ═══════════════════════════════════════════════════════════════
::  XH-Agent Windows 一键启动脚本
::  用法: 双击 run.bat 或在终端执行 .\run.bat
:: ═══════════════════════════════════════════════════════════════

title XH-Agent Server

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║     XH-Agent 领域知识个性化生成系统 v0.1.0               ║
echo ║     多智能体协同决策 — 揭榜挂帅 XH-202630                ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

:: ── 1. 检测 Python 环境 ──
echo [1/5] 检测 Python 环境...

set "PYTHON_CMD="

:: 优先查找 python3，其次 python
where python3 >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "delims=" %%i in ('where python3') do set "PYTHON_CMD=%%i"
    goto :found_python
)

where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "delims=" %%i in ('where python') do set "PYTHON_CMD=%%i"
    goto :found_python
)

echo [ERROR] 未检测到 Python，请先安装 Python 3.10+
echo         下载地址: https://www.python.org/downloads/
pause
exit /b 1

:found_python
echo    Python 路径: %PYTHON_CMD%

:: 版本检查
for /f "tokens=2" %%v in ('"%PYTHON_CMD%" --version 2^>^&1') do set "PY_VER=%%v"
echo    Python 版本: !PY_VER!
for /f "tokens=1 delims=." %%a in ("!PY_VER!") do set "PY_MAJOR=%%a"
for /f "tokens=2 delims=." %%a in ("!PY_VER!") do set "PY_MINOR=%%a"

if !PY_MAJOR! LSS 3 (
    echo [ERROR] Python 版本过低 (!PY_VER!)，需要 3.10+
    pause
    exit /b 1
)
if !PY_MAJOR! EQU 3 if !PY_MINOR! LSS 10 (
    echo [WARN]  Python !PY_VER! 低于推荐版本 3.10，部分特性可能不可用
)

:: ── 2. 设置 PYTHONPATH ──
echo.
echo [2/5] 设置环境变量...
set "PYTHONPATH=%~dp0backend;%PYTHONPATH%"
echo    PYTHONPATH = %~dp0backend

:: ── 3. 检查 .env 配置文件 ──
echo.
echo [3/5] 检查配置...

if exist "%~dp0.env" (
    echo    .env 已存在，使用现有配置
) else (
    echo    .env 不存在，正在从 .env.example 创建...
    if exist "%~dp0.env.example" (
        copy "%~dp0.env.example" "%~dp0.env" >nul
        echo    [DONE] .env 已创建，默认运行在演示模式
        echo           编辑 .env 填入 LLM_API_KEY 以启用真实 LLM 调用
    ) else (
        echo    [WARN] .env.example 也不存在，将使用硬编码默认值（演示模式）
    )
)

:: ── 4. 检查关键依赖 ──
echo.
echo [4/5] 检查依赖...

"%PYTHON_CMD%" -c "import fastapi, uvicorn, loguru, dotenv, chromadb, openai" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo    缺少依赖，正在安装...
    echo.
    "%PYTHON_CMD%" -m pip install -r requirements.txt -q
    if %ERRORLEVEL% NEQ 0 (
        echo    [ERROR] 依赖安装失败，请手动执行:
        echo            pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo    [DONE] 依赖安装完成
) else (
    echo    核心依赖已就绪
)

:: ── 5. 启动服务 ──
echo.
echo [5/5] 启动服务...
echo.
echo ═══════════════════════════════════════════════════════════
echo   服务地址 : http://localhost:8000
echo   API 文档 : http://localhost:8000/docs
echo   健康检查 : http://localhost:8000/health
echo.
echo   按 Ctrl+C 停止服务
echo ═══════════════════════════════════════════════════════════
echo.

:: 切换到项目根目录后启动
cd /d "%~dp0"
"%PYTHON_CMD%" -m uvicorn main:app --host 0.0.0.0 --port 8000 --log-level info

:: ── 退出 ──
echo.
echo 服务已停止。
pause
endlocal
