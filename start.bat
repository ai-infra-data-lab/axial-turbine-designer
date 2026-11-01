@echo off
setlocal
cd /d "%~dp0"
if exist "..\.runtime\python\python.exe" (
  "..\.runtime\python\python.exe" server.py --open
) else (
  python server.py --open
)
pause
