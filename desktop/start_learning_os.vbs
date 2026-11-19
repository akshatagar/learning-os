' Launches Learning OS in its desktop window with no console window.
' Double-click it, or put a shortcut to it in the Startup folder
' (Win+R, shell:startup) to open the app at login.
' It runs the base interpreter's pythonw.exe on desktop\launch.pyw, because
' uv's .venv\Scripts\pythonw.exe is a console program despite its name.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(here)

' The base interpreter's folder is the "home" line of .venv\pyvenv.cfg.
Set cfg = fso.OpenTextFile(root & "\.venv\pyvenv.cfg", 1)
pyhome = ""
Do Until cfg.AtEndOfStream
  line = cfg.ReadLine
  If LCase(Trim(Split(line, "=")(0))) = "home" Then pyhome = Trim(Mid(line, InStr(line, "=") + 1))
Loop
cfg.Close

shell.CurrentDirectory = root
shell.Run """" & pyhome & "\pythonw.exe"" """ & here & "\launch.pyw""", 1, False
