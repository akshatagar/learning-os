' Launches Learning OS in its desktop window with no console window.
' Double-click it, or put a shortcut to it in the Startup folder
' (Win+R, shell:startup) to open the app at login.
' It runs from the project folder, wherever that is.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
shell.CurrentDirectory = root
shell.Run """" & root & "\.venv\Scripts\pythonw.exe"" -m web.shell", 1, False
