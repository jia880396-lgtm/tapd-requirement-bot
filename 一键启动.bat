@echo off
chcp 65001 >nul
cd /d "%~dp0backend"

echo ==========================================================
echo          TAPD 需求处理机器人 - 一键启动
echo ==========================================================
echo.

REM ---------- 环境检查 ----------
if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境 .venv\Scripts\python.exe
    echo 请先执行: python -m venv .venv
    pause
    exit /b 1
)
if not exist "run.py" (
    echo [错误] 未找到启动文件 run.py
    pause
    exit /b 1
)

set PORT=8030
set HEALTH_URL=http://localhost:%PORT%/api/health

REM ---------- 检查端口是否被占用 ----------
for /f %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"') do set EXISTING_PID=%%p

if defined EXISTING_PID (
    echo 检测到 %PORT% 端口已被进程 PID=%EXISTING_PID% 占用，正在验证后端是否健康...
    call :health_ok
    if "%HEALTH_OK%"=="1" (
        echo 后端已在正常运行（健康），直接打开浏览器。
        start "" http://localhost:%PORT%
        goto :done
    )
    echo 端口占用但后端无响应（可能是陈旧/异常进程），正在终止并重新启动...
    taskkill /PID %EXISTING_PID% /F >nul 2>&1
    timeout /t 2 >nul
)

REM ---------- 启动后端 ----------
echo 正在启动后端服务（端口 %PORT%）...
echo 访问地址: http://localhost:%PORT%
echo 默认账号: admin / admin123
echo ----------------------------------------
start /min "" .venv\Scripts\python.exe run.py

REM ---------- 等待健康检查通过（最多 60 秒） ----------
echo 等待后端就绪...
set /a WAIT=0
:waitloop
set /a WAIT+=1
if %WAIT% gtr 60 (
    echo [警告] 后端启动超时，请检查 backend 目录下的运行日志。
    echo 可手动运行 scripts\start_server.bat 查看具体报错。
    pause
    exit /b 1
)
call :health_ok
if "%HEALTH_OK%"=="1" goto :started
timeout /t 1 >nul
goto :waitloop

:started
echo 后端已就绪！正在打开浏览器...
start "" http://localhost:%PORT%
goto :done

:done
echo ----------------------------------------
echo 浏览器已打开。如需停止服务，请运行 scripts\stop_server.bat
echo ----------------------------------------
echo 本窗口 3 秒后关闭...
timeout /t 3 >nul
exit /b 0

REM ---------- 健康检查子过程：将 HEALTH_OK 设为 1（健康）或 0（异常） ----------
REM 注意：$ProgressPreference='SilentlyContinue' 用于屏蔽 Invoke-WebRequest 的进度提示，
REM 否则进度文字会被 for /f 误当成返回值，导致误判为不健康。
:health_ok
set HEALTH_OK=0
for /f %%c in ('powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { $r = Invoke-WebRequest -Uri '%HEALTH_URL%' -UseBasicParsing -TimeoutSec 3; if ($r.StatusCode -eq 200) { Write-Output 1 } else { Write-Output 0 } } catch { Write-Output 0 }"') do set HEALTH_OK=%%c
goto :eof
