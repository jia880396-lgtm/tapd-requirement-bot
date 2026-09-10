@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "backend\.venv\Scripts\python.exe" (
  echo [错误] 尚未安装，请先运行 install_new_pc.bat
  pause
  exit /b 1
)
if not exist "backend\static_dist\index.html" (
  echo [错误] 未找到前端构建产物，请先运行 install_new_pc.bat
  pause
  exit /b 1
)
set PORT=8030
for /f %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"') do set EXISTING_PID=%%p
if defined EXISTING_PID (
  echo 服务已运行，访问 http://localhost:%PORT%
  start "" http://localhost:%PORT%
  exit /b 0
)
echo 正在启动服务：http://localhost:%PORT%
start "TAPD Requirement Bot" /min cmd /c "cd /d "%~dp0backend" && .venv\Scripts\python.exe run.py"
set /a WAIT=0
:wait
set /a WAIT+=1
if %WAIT% gtr 60 goto :timeout
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { $r=Invoke-WebRequest -Uri 'http://localhost:%PORT%/api/health' -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -eq 200){exit 0}else{exit 1} } catch { exit 1 }"
if not errorlevel 1 (
  echo 服务已就绪。
  echo 本机访问：http://localhost:%PORT%
  echo 局域网访问：http://新电脑局域网IP:%PORT%
  start "" http://localhost:%PORT%
  exit /b 0
)
timeout /t 1 >nul
goto :wait
:timeout
echo [警告] 服务启动超时，请运行 backend\run.py 查看错误。
pause
exit /b 1
