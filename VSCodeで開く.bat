@echo off
chcp 65001 > nul
cd /d "%~dp0"

:: VS Codeのパスを自動検出
set VSCODE=""
if exist "%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe" (
    set VSCODE="%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"
) else if exist "C:\Program Files\Microsoft VS Code\Code.exe" (
    set VSCODE="C:\Program Files\Microsoft VS Code\Code.exe"
)

if %VSCODE%=="" (
    echo VS Code が見つかりません。手動で開いてください。
    explorer .
    pause
) else (
    echo VS Code を開いています...
    start "" %VSCODE% "%~dp0"
)
