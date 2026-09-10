@echo off
setlocal
set PORT=8030
for /f %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"') do set PID=%%p
if defined PID (
  taskkill /PID %PID% /F >nul 2>&1
  echo 已停止服务 PID=%PID%。
) else (
  echo 未发现运行中的 8030 服务。
)
pause
