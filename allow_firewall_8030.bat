@echo off
chcp 65001 >nul
netsh advfirewall firewall add rule name="TAPD Requirement Bot 8030" dir=in action=allow protocol=TCP localport=8030 >nul
if errorlevel 1 (
  echo 添加失败：请右键本文件，选择“以管理员身份运行”。
) else (
  echo 已放行 TCP 8030，局域网用户可访问。
)
pause
