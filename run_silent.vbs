' SoftMacro - silent launcher (no console window)
' Double-click this to start SoftMacro invisibly; it lives in the system tray.
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.Run """" & base & "\venv\Scripts\pythonw.exe"" """ & base & "\app.py""", 0, False
