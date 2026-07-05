@echo off
rem Coderain — double-click to launch the web app (opens in your browser).
rem First run creates a .venv and installs dependencies automatically; this
rem console shows the progress and the address, then stays open as the server log.
rem   Coderain.bat            web app (default)
rem   Coderain.bat --cli      terminal / text mode
rem   Coderain.bat --gui      retro Tkinter UI (easter egg)
rem start.py finds/creates the .venv and re-launches itself there, so we just
rem hand off to whatever Python is on PATH (the launcher does the rest).
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py start.py %*
) else (
    python start.py %*
)
