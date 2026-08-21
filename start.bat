@echo off
setlocal enabledelayedexpansion

:: XH-Agent Windows launcher
:: Usage: double-click start.bat, or run .\start.bat from this directory

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
    echo   [..] Virtualenv not found, creating .venv ...
    where python >nul 2>&1
    if errorlevel 1 (
        echo.
        echo [ERROR] Python was not found on PATH.
        echo Install Python 3.11-3.13 and enable "Add python.exe to PATH".
        echo.
        pause
        exit /b 1
    )
    python -m venv "%PROJECT_ROOT%.venv"
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to create the virtualenv.
        echo Run manually: python -m venv .venv
        echo.
        pause
        exit /b 1
    )
    echo   [OK] Virtualenv created
)

echo   [OK] Using: %VENV_PY%

:: -- 2. Check .env -------------------------------------------------------
echo.
echo [2/4] Check .env config ...

if exist "%PROJECT_ROOT%.env" goto env_ready
if exist "%PROJECT_ROOT%.env.example" copy /y "%PROJECT_ROOT%.env.example" "%PROJECT_ROOT%.env" >nul
if exist "%PROJECT_ROOT%.env" (
    echo   [OK] .env created from .env.example (demo mode by default)
) else (
    echo   [WARN] .env.example not found, using built-in defaults
)
goto dependencies

:env_ready
echo   [OK] .env exists

:: -- 3. Check dependencies ------------------------------------------------
:dependencies
echo.
echo [3/4] Check dependencies ...

"%VENV_PY%" -c "import fastapi, uvicorn, loguru, dotenv, chromadb, openai" 2>nul
if not errorlevel 1 goto dependencies_ready
echo   [..] Missing dependencies, installing from requirements.txt ...
"%VENV_PY%" -m pip install -r requirements.txt -q
if errorlevel 1 goto dependencies_failed
echo   [OK] Dependencies installed
goto start_server

:dependencies_ready
echo   [OK] Dependencies ready
goto start_server

:dependencies_failed
echo   [ERROR] Install failed. Run manually:
echo           .venv\Scripts\python.exe -m pip install -r requirements.txt
pause
exit /b 1

:: -- 4. Start server ------------------------------------------------------
:start_server
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
