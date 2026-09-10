@echo off
echo ========================================
echo   停止 TAPD 需求处理机器人...
echo ========================================
echo.

set "found=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8030 ^| findstr LISTENING') do (
    echo 正在终止进程 PID=%%a
    taskkill /PID %%a /F
    set "found=1"
)

if "%found%"=="0" (
    echo 未发现运行中的服务（端口 8030 未被占用）
) else (
    echo 服务已停止
)
echo.
pause
