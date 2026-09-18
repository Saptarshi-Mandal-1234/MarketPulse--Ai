@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" -m marketpulse.models.train
if errorlevel 1 goto end
"%~dp0.venv\Scripts\python.exe" scripts\verify_models.py
:end
echo.
pause
