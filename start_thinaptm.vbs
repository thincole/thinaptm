Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "E:\ThinAptm0707"
WshShell.Run "pythonw thin_aptm.py", 0, False
