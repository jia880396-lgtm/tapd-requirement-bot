@echo off
echo ========================================
echo   重启 TAPD 需求处理机器人...
echo ========================================
echo.

call "%~dp0stop_server.bat"
echo 等待 2 秒...
ping -n 3 127.0.0.1 >nul
echo.
start "TAPD 需求处理机器人" "%~dp0start_server.bat"
echo 服务已在新窗口中启动
echo.
pause
