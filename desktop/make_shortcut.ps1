# Creates "Learning OS.lnk" in the project folder and in the Start menu.
# Right-click either one and choose "Pin to taskbar" (Windows does not let
# scripts pin). Run again if the project folder moves:
#
#   powershell -ExecutionPolicy Bypass -File desktop\make_shortcut.ps1
#
# The shortcut runs the base interpreter's pythonw.exe on desktop\launch.pyw.
# uv's .venv\Scripts\pythonw.exe is a console program despite its name, so
# using it would open a terminal behind the app.

$root = Split-Path -Parent $PSScriptRoot
$cfg = Join-Path $root ".venv\pyvenv.cfg"
$icon = Join-Path $PSScriptRoot "learning-os.ico"
$launcher = Join-Path $PSScriptRoot "launch.pyw"

if (-not (Test-Path $cfg)) { throw "No $cfg. Run 'uv sync' in $root first." }
if (-not (Test-Path $icon)) { throw "No $icon. Run 'uv run python desktop\make_icon.py' first." }

$home_ = ((Get-Content $cfg | Where-Object { $_ -match '^\s*home\s*=' }) -split '=', 2)[1].Trim()
$pythonw = Join-Path $home_ "pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "No windowless Python at $pythonw." }

$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @($root, $startMenu)) {
    $path = Join-Path $dir "Learning OS.lnk"
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $pythonw
    $link.Arguments = "`"$launcher`""
    $link.WorkingDirectory = $root
    $link.IconLocation = "$icon,0"
    $link.Description = "Learning OS"
    $link.Save()
    Write-Output "wrote $path"
}
