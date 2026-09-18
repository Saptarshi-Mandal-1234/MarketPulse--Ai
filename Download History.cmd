@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" -m marketpulse.ingestion.download
echo.
pause
