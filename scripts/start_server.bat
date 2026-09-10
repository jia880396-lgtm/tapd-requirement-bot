@echo off
cd /d "%~dp0..\backend"
echo ========================================
echo   TAPD 需求处理机器人 启动中...
echo ========================================
echo.
echo 工作目录: %CD%
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到 Python 虚拟环境 .venv
    pause
    exit /b 1
)

if not exist "run.py" (
    echo [错误] 未找到启动文件 run.py
    pause
    exit /b 1
)

echo 正在启动后端服务...
echo 访问地址: http://localhost:8030
echo 默认账号: admin / admin123
echo 按 Ctrl+C 可停止服务
echo ----------------------------------------
.venv\Scripts\python.exe run.py
echo.
echo 服务已停止
pause
