@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ==========================================================
echo   TAPD 需求智能处理 Bot - 新电脑一键安装
 echo ==========================================================
echo.
where python >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 Python，请先安装 Python 3.11+ 并勾选 Add Python to PATH。
  pause
  exit /b 1
)
where node >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 Node.js，请先安装 Node.js 18+。
  pause
  exit /b 1
)
if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/5] 创建 Python 虚拟环境...
  python -m venv backend\.venv
  if errorlevel 1 goto :fail
)
echo [2/5] 安装后端依赖...
backend\.venv\Scripts\python.exe -m pip install --upgrade pip
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 goto :fail
if not exist "backend\data" mkdir "backend\data"
if not exist "backend\.env" (
  echo [3/5] 创建配置文件...
  copy /Y "backend\.env.example" "backend\.env" >nul
) else (
  echo [3/5] 已存在 backend\.env，保留现有配置。
)
echo [4/5] 安装前端依赖...
cd frontend
call npm install
if errorlevel 1 goto :fail
 echo [5/5] 构建并部署前端...
call npm run build
if errorlevel 1 goto :fail
cd ..
if not exist "backend\static_dist" mkdir "backend\static_dist"
xcopy "frontend\dist\*" "backend\static_dist\" /E /I /Y /Q >nul
if errorlevel 1 goto :fail
echo.
echo ==========================================================
echo 安装完成！
echo 配置已随包完整迁移（backend\.env 已含全部 key），无需重新填写。
echo 直接双击 start_new_pc.bat 启动即可。
echo ==========================================================
pause
exit /b 0
:fail
cd /d "%~dp0"
echo.
echo [错误] 安装过程失败，请查看上方错误信息。
pause
exit /b 1
