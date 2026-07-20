@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: =============================================================================
::  XH-Agent Windows 启动脚本
::  用法：双击 start.bat 或在终端中运行 .\start.bat
:: =============================================================================

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║        XH-Agent · 领域知识个性化生成系统 v0.1.0             ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

:: ── 获取脚本所在目录（项目根目录）─────────────────────────────────────────
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

:: ── Step 0: 检测 .env 文件并加载环境变量 ──────────────────────────────────
echo [1/4] 检测环境配置 ...

:: 优先 backend\.env，其次根目录 .env
if exist "backend\.env" (
    set "ENV_FILE=backend\.env"
) else if exist ".env" (
    set "ENV_FILE=.env"
) else if exist ".env.example" (
    echo.
    echo   [!] 未找到 .env 文件
    echo   [!] 正在从 .env.example 复制默认配置 ...
    copy /y ".env.example" ".env" >nul
    if exist ".env" (
        set "ENV_FILE=.env"
        echo   [√] 已生成 .env，使用默认配置
    ) else (
        set "ENV_FILE="
        echo   [√] 将使用 config.py 硬编码默认值
    )
) else (
    echo   [!] 未找到任何配置文件，使用 config.py 默认值
)

:: 加载 .env 中的环境变量（仅设置未定义的变量，不覆盖已有环境变量）
if defined ENV_FILE (
    echo   [√] 加载配置: %ENV_FILE%
    for /f "usebackq tokens=1,2 delims==" %%a in ("%ENV_FILE%") do (
        set "line=%%a"
        :: 跳过空行和注释行
        if not "!line!"=="" (
            if not "!line:~0,1!"=="#" (
                if not "!line:~0,1!"==";" (
                    if not "!line:~0,2!"=="//" (
                        :: 仅当变量未设置时才从文件加载
                        if not defined %%a set "%%a=%%b"
                    )
                )
            )
        )
    )
)

:: ── 模式检测 ──────────────────────────────────────────────────────────────
if "%LLM_API_KEY%"=="" (
    set "RUN_MODE=🔶 模拟模式（未检测到 LLM_API_KEY）"
) else (
    set "RUN_MODE=🔷 真实模式（LLM_API_KEY 已配置）"
)
echo   [!] 运行模式: %RUN_MODE%
echo.

:: ── Step 1: ruff 代码规范检查 ─────────────────────────────────────────────
echo [2/4] ruff check 代码规范校验 ...

where ruff >nul 2>&1
if %errorlevel% neq 0 (
    echo   [!] 未安装 ruff，跳过代码检查
    echo   [!] 安装方式: pip install ruff
) else (
    ruff check backend\ 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo ╔══════════════════════════════════════════════════════════════╗
        echo ║  [X] ruff 检查未通过！请修复以上问题后重新启动            ║
        echo ║      可运行 ruff check backend\ --fix 自动修复部分问题   ║
        echo ╚══════════════════════════════════════════════════════════════╝
        pause
        exit /b 1
    )
    echo   [√] 代码规范检查通过
)
echo.

:: ── Step 2: 校验 Python 环境 ──────────────────────────────────────────────
echo [3/4] 检查 Python 环境 ...

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [X] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: 获取 Python 版本
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo   [√] Python %PY_VER%

:: 检查关键依赖
python -c "import fastapi, uvicorn, loguru; print('[√] 核心依赖就绪')" 2>nul
if %errorlevel% neq 0 (
    echo   [!] 缺少依赖，正在安装 ...
    cd /d "%PROJECT_ROOT%backend"
    pip install -e ".[dev]" 2>&1
    if %errorlevel% neq 0 (
        echo   [X] 依赖安装失败
        pause
        exit /b 1
    )
    cd /d "%PROJECT_ROOT%"
)
echo.

:: ── Step 3: 启动后端服务 ──────────────────────────────────────────────────
echo [4/4] 启动 FastAPI 服务 ...
echo.

:: 切换到 backend 目录以正确加载 src 包
cd /d "%PROJECT_ROOT%backend"

:: 设置端口默认值
if "%PORT%"=="" set "PORT=8000"
if "%HOST%"=="" set "HOST=0.0.0.0"

:: 运行模式提示
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                                                            ║
if "%LLM_API_KEY%"=="" (
    echo ║   🔶 无 API Key — 自动进入模拟运行模式                   ║
    echo ║                                                            ║
    echo ║   所有 LLM 调用返回 schema 完备的内置模拟数据             ║
    echo ║   设置 LLM_API_KEY 环境变量可启用真实 LLM 调用            ║
) else (
    echo ║   🔷 真实 LLM 模式 — %LLM_PROVIDER%/%LLM_MODEL%           ║
)
echo ║                                                            ║
echo ║   API 文档: http://localhost:%PORT%/docs                    ║
echo ║   健康检查: http://localhost:%PORT%/health                   ║
echo ║   Ctrl+C 停止服务                                          ║
echo ║                                                            ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

:: 启动 uvicorn（优先 src/main.py，否则 src.api.main:app）
if exist "src\main.py" (
    python -m uvicorn src.main:app --host %HOST% --port %PORT% --reload
) else (
    python -m uvicorn src.api.main:app --host %HOST% --port %PORT% --reload
)

:: ── 服务终止 ──────────────────────────────────────────────────────────────
echo.
echo ═══════════════════════════════════════════════════════════════
echo   服务已停止
echo ═══════════════════════════════════════════════════════════════
pause
