@echo off
rem Coderain — double-click to launch the desktop GUI.
rem Uses the project venv if present (pythonw = no console window), else falls back
rem to the system launcher. Pass --cli for text mode: Coderain.bat --cli
cd /d "%~dp0"
if /i "%~1"=="--cli" goto cli

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "start.py" %*
) else (
    start "" pythonw "start.py" %*
)
goto :eof

:cli
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "start.py" --cli
) else (
    py "start.py" --cli
)
