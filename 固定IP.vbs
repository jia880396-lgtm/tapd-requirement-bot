Set objShell = CreateObject("Shell.Application")
objShell.ShellExecute "powershell.exe", _
    "-NoProfile -ExecutionPolicy Bypass -File ""set_static_ip.ps1""", _
    ".", "runas", 1
