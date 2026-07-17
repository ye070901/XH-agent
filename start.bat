@echo off
echo ============================================================
echo  多智能体协同决策系统 MVP
echo ============================================================
echo.

:: 检查 .env 文件
if not exist .env (
    echo [!] 未找到 .env 文件，正在从 .env.example 复制...
    copy .env.example .env
    echo [!] 请编辑 .env 文件，填写你的 LLM_API_KEY
    echo [!] 如果跳过此步骤，系统将以演示模式运行（返回模拟数据）
    echo.
    pause
)

:: 安装依赖（如果还没装）
echo [1/3] 检查依赖...
cd backend
pip install -e ".[dev]" streamlit -q 2>nul
cd ..

:: 启动后端
echo [2/3] 启动后端 API (端口 8000)...
start "Backend API" cmd /c "cd backend && python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload"
timeout /t 3 /nobreak >nul

:: 启动前端
echo [3/3] 启动 Streamlit 前端 (端口 8501)...
start "Streamlit Frontend" cmd /c "streamlit run frontend/streamlit/app.py"
timeout /t 3 /nobreak >nul

echo.
echo ============================================================
echo  启动完成！
echo   后端: http://localhost:8000
echo   前端: http://localhost:8501
echo  API 文档: http://localhost:8000/docs
echo ============================================================
echo.
echo 按任意键退出此窗口（不会关闭后端和前端）...
pause >nul
