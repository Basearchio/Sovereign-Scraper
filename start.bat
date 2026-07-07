@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Run with the project venv python directly if it exists. This avoids re-launching
rem into the venv on every start (os.execv), which drops the first keystroke on Windows.
rem Only the very first run (no venv yet) uses system python to bootstrap once.
if exist ".venv\Scripts\python.exe" goto USEVENV
python start.py %*
goto DONE
:USEVENV
".venv\Scripts\python.exe" start.py %*
:DONE
pause
