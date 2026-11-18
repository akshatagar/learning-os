# Creates "Learning OS.lnk" in the project folder and in the Start menu.
# Right-click either one and choose "Pin to taskbar" (Windows does not let
# scripts pin). Run again if the project folder moves:
#
#   powershell -ExecutionPolicy Bypass -File desktop\make_shortcut.ps1

$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$icon = Join-Path $PSScriptRoot "learning-os.ico"

if (-not (Test-Path $pythonw)) { throw "No $pythonw. Run 'uv sync' in $root first." }
if (-not (Test-Path $icon)) { throw "No $icon. Run 'uv run python desktop\make_icon.py' first." }

$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @($root, $startMenu)) {
    $path = Join-Path $dir "Learning OS.lnk"
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $pythonw
    $link.Arguments = "-m web.shell"
    $link.WorkingDirectory = $root
    $link.IconLocation = "$icon,0"
    $link.Description = "Learning OS"
    $link.Save()
    Write-Output "wrote $path"
}
