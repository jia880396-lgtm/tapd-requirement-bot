# 固定静态IP地址脚本（需管理员权限运行）
# ⚠️ 以下 IP 均为占位符，请替换为你本机的内网静态 IP / 网关 / DNS 后再运行
$ErrorActionPreference = 'Stop'

Write-Host "========================================================"
Write-Host "  正在固定本机IP地址"
Write-Host "========================================================"
Write-Host ""

try {
    # 1. 禁用DHCP
    Write-Host "[1/4] 禁用DHCP..."
    Set-NetIPInterface -InterfaceAlias "WLAN" -Dhcp Disabled
    Write-Host "  [OK] DHCP已禁用"

    # 2. 移除现有IP配置
    Write-Host "[2/4] 清除现有IP配置..."
    Get-NetIPAddress -InterfaceAlias "WLAN" -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
    Get-NetRoute -InterfaceAlias "WLAN" -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "  [OK] 已清除旧配置"

    # 3. 设置静态IP
    Write-Host "[3/4] 设置静态IP: 192.168.x.232 ..."
    New-NetIPAddress -InterfaceAlias "WLAN" -IPAddress "192.168.x.232" -PrefixLength 22 -DefaultGateway "192.168.x.1" | Out-Null
    Write-Host "  [OK] 静态IP已设置"

    # 4. 设置DNS
    Write-Host "[4/4] 设置DNS: 192.168.x.1 ..."
    Set-DnsClientServerAddress -InterfaceAlias "WLAN" -ServerAddresses "192.168.x.1"
    Write-Host "  [OK] DNS已设置"

    Write-Host ""
    Write-Host "========================================================"
    Write-Host "  固定IP设置成功！"
    Write-Host "========================================================"
    Write-Host ""
    Write-Host "  本机固定IP: 192.168.x.232"
    Write-Host "  局域网访问: http://192.168.x.232:8030"
    Write-Host ""
} catch {
    Write-Host ""
    Write-Host "  [错误] $($_.Exception.Message)"
    Write-Host ""
    Write-Host "  正在回滚：恢复DHCP..."
    try {
        Set-NetIPInterface -InterfaceAlias "WLAN" -Dhcp Enabled
        Set-DnsClientServerAddress -InterfaceAlias "WLAN" -ResetServerAddresses
        Write-Host "  [OK] 已恢复DHCP，网络应已恢复"
    } catch {
        Write-Host "  [警告] 恢复DHCP失败，请手动检查网络设置"
    }
}
Write-Host ""
Write-Host "按任意键退出..."
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
