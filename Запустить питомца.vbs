' Starts the desktop pet without a console window.
' The path is taken from this file's location, so the pet folder can live anywhere.
'
' Python search order (the first pythonw.exe found wins; among several versions
' in one place the newest is taken):
'   1) C:\Python*                         - manual installs to the drive root
'   2) %LOCALAPPDATA%\Programs\Python\*   - python.org installer, "just for me"
'   3) %ProgramFiles%\Python*, %ProgramFiles(x86)%\Python*  - "for all users"
'   4) Anaconda / Miniconda in the user profile or ProgramData
'   5) py launcher (pyw.exe in C:\Windows) - picks an installed Python itself
'   6) pythonw / pyw from PATH            - last resort
' The Microsoft Store Python is skipped on purpose: programs it starts get a
' redirected %APPDATA%, and the pet then cannot see the "Claude is thinking" markers.

Option Explicit

Dim shell, fso, here, script, env, root, candidate
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

here = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(here, "claude_pet.pyw")

If Not fso.FileExists(script) Then
    MsgBox "File not found:" & vbCrLf & script, vbExclamation, "Claude pet"
    WScript.Quit 1
End If

' 1) C:\Python* (for example C:\Python or C:\Python312)
TryBest NewestIn("C:\", "Python")

' 2) python.org installer for the current user
TryBest NewestIn(shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python"), "Python")

' 3) python.org installer for all users
For Each env In Array("%ProgramFiles%", "%ProgramFiles(x86)%")
    root = shell.ExpandEnvironmentStrings(env)
    If InStr(root, "%") = 0 Then TryBest NewestIn(root, "Python")
Next

' 4) Anaconda / Miniconda
For Each env In Array("%USERPROFILE%\anaconda3", "%USERPROFILE%\miniconda3", _
                      "%ProgramData%\anaconda3", "%ProgramData%\miniconda3")
    TryRun fso.BuildPath(shell.ExpandEnvironmentStrings(env), "pythonw.exe")
Next

' 5) py launcher installed by python.org (not the Store alias)
TryRun shell.ExpandEnvironmentStrings("%WINDIR%\pyw.exe")

' 6) Last resort: pythonw / pyw from PATH
On Error Resume Next
For Each candidate In Array("pythonw", "pyw")
    Err.Clear
    shell.Run """" & candidate & """ """ & script & """", 0, False
    If Err.Number = 0 Then WScript.Quit 0
Next
On Error GoTo 0

MsgBox "Python not found." & vbCrLf & vbCrLf & _
       "Install Python 3 from https://www.python.org (check ""Add to PATH"")," & vbCrLf & _
       "then run in a command prompt:  pip install pillow", vbExclamation, "Claude pet"
WScript.Quit 1

' Newest pythonw.exe in subfolders of root whose names start with prefix
' (Python313 beats Python312, Python310 beats Python39); "" if none.
Function NewestIn(root, prefix)
    Dim sub_, exe, bestVer, ver
    NewestIn = ""
    bestVer = -1
    If Not fso.FolderExists(root) Then Exit Function
    On Error Resume Next   ' folders without access are simply skipped
    For Each sub_ In fso.GetFolder(root).SubFolders
        If LCase(Left(sub_.Name, Len(prefix))) = LCase(prefix) Then
            exe = fso.BuildPath(sub_.Path, "pythonw.exe")
            If fso.FileExists(exe) Then
                ver = VersionOf(Mid(sub_.Name, Len(prefix) + 1))
                If ver > bestVer Then
                    bestVer = ver
                    NewestIn = exe
                End If
            End If
        End If
    Next
    On Error GoTo 0
End Function

' "312" -> 312, "3.12" -> 312, "" -> 0 (a plain "Python" folder)
Function VersionOf(s)
    Dim i, ch, digits
    digits = ""
    For i = 1 To Len(s)
        ch = Mid(s, i, 1)
        If ch >= "0" And ch <= "9" Then digits = digits & ch
    Next
    If digits = "" Then
        VersionOf = 0
    Else
        VersionOf = CLng(Left(digits, 6))
    End If
End Function

Sub TryBest(exe)
    If exe <> "" Then TryRun exe
End Sub

Sub TryRun(exe)
    If fso.FileExists(exe) Then
        shell.Run """" & exe & """ """ & script & """", 0, False
        WScript.Quit 0
    End If
End Sub
