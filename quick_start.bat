@echo off
chcp 65001 >nul
title TAPD 需求智能处理 Agent - 快速启动
cd /d "%~dp0"

:menu
cls
echo ========================================
echo   TAPD 需求智能处理 Agent
echo   快速启动面板
echo ========================================
echo.
echo   [1] 启动服务        （启动后端，访问 http://localhost:8030）
echo   [2] 停止服务
echo   [3] 重启服务
echo   [4] 构建并部署前端  （npm build 后拷贝到后端静态目录）
echo   [5] 打开浏览器
echo   [6] 查看运行状态
echo   [0] 退出
echo.
set /p choice=请输入选项编号：

if "%choice%"=="1" goto start
if "%choice%"=="2" goto stop
if "%choice%"=="3" goto restart
if "%choice%"=="4" goto build
if "%choice%"=="5" goto open
if "%choice%"=="6" goto status
if "%choice%"=="0" exit
goto menu

:start
echo.
call "%~dp0scripts\start_server.bat"
goto menu

:stop
echo.
call "%~dp0scripts\stop_server.bat"
goto menu

:restart
echo.
call "%~dp0scripts\restart_server.bat"
goto menu

:build
echo.
call "%~dp0scripts\build_and_deploy.bat"
goto menu

:open
echo.
echo 正在打开浏览器...
start http://localhost:8030
goto menu

:status
echo.
echo ---------- 端口监听状态 ----------
set PORT=8030
if exist "%~dp0backend\.env" (
    for /f "tokens=1,2 delims==" %%a in (%~dp0backend\.env) do (
        if /i "%%a"=="PORT" set PORT=%%b
    )
)
netstat -ano | findstr :%PORT% | findstr LISTENING >nul
if errorlevel 1 (
    echo [未运行] 端口 %PORT% 无监听
) else (
    echo [运行中] 端口 %PORT% 有监听：
    netstat -ano | findstr :%PORT% | findstr LISTENING
)
echo.
pause
goto menu
