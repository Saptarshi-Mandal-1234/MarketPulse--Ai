@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" scripts\check_health.py
pause
