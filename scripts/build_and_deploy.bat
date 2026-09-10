@echo off
cd /d "%~dp0..\frontend"
echo ========================================
echo   构建并部署前端...
echo ========================================
echo.
echo 工作目录: %CD%
echo.

if not exist "node_modules" (
    echo [错误] 未找到 node_modules，请先执行 npm install
    pause
    exit /b 1
)

echo 正在构建前端...
call npm run build
if errorlevel 1 (
    echo.
    echo [错误] 前端构建失败
    pause
    exit /b 1
)

echo.
echo 正在部署到后端静态目录...
set "BACKEND_DIR=%~dp0..\backend"
if exist "%BACKEND_DIR%\static_dist" rmdir /s /q "%BACKEND_DIR%\static_dist"
xcopy "dist" "%BACKEND_DIR%\static_dist\" /E /I /Y /Q
if errorlevel 1 (
    echo [错误] 部署失败
    pause
    exit /b 1
)

echo.
echo ========================================
echo   构建部署完成！
echo ========================================
echo 如需生效，请重启后端服务（运行 restart_server.bat）
echo.
pause
