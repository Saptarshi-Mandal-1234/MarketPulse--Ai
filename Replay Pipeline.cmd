@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" -m marketpulse.pipeline --replay
echo.
pause
