@echo off
setlocal enabledelayedexpansion

:: XH-Agent Windows one-click launcher (uses project-local .venv)
:: Usage: double-click run.bat, or run .\run.bat

title XH-Agent Server

set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

set "VENV_PY=%PROJECT_ROOT%.venv\Scripts\python.exe"

echo.
echo ============================================================
echo   XH-Agent  -  domain knowledge personalized generation
echo   multi-agent decision system  -  XH-202630
echo ============================================================
echo.

:: -- 1. Check virtualenv -------------------------------------------------
echo [1/4] Check virtualenv ...

if not exist "%VENV_PY%" (
    echo.
    echo [ERROR] Virtualenv not found: .venv\Scripts\python.exe
    echo.
    echo Please set it up first:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo   [OK] Using: %VENV_PY%

:: -- 2. Check .env -------------------------------------------------------
echo.
echo [2/4] Check .env config ...

if exist "%PROJECT_ROOT%.env" (
    echo   [OK] .env exists
) else (
    if exist "%PROJECT_ROOT%.env.example" (
        copy /y "%PROJECT_ROOT%.env.example" "%PROJECT_ROOT%.env" >nul
        echo   [OK] .env created from .env.example (demo mode by default)
    ) else (
        echo   [WARN] .env.example not found, using built-in defaults
    )
)

:: -- 3. Check dependencies ------------------------------------------------
echo.
echo [3/4] Check dependencies ...

"%VENV_PY%" -c "import fastapi, uvicorn, loguru, dotenv, chromadb, openai" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo   [..] Missing dependencies, installing from requirements.txt ...
    "%VENV_PY%" -m pip install -r requirements.txt -q
    if %ERRORLEVEL% NEQ 0 (
        echo   [ERROR] Install failed. Run manually:
        echo           .venv\Scripts\python.exe -m pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo   [OK] Dependencies installed
) else (
    echo   [OK] Dependencies ready
)

:: -- 4. Start server ------------------------------------------------------
echo.
echo [4/4] Starting server ...
echo.
echo ============================================================
echo   API docs  : http://localhost:8000/docs
echo   Health    : http://localhost:8000/health
echo   Press Ctrl+C to stop
echo ============================================================
echo.

"%VENV_PY%" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

echo.
echo Server stopped.
pause
endlocal
