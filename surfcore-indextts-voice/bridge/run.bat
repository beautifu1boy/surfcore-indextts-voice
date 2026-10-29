@echo off
rem Standalone launcher for the bridge (dev / debugging).
rem In production the SurfCore voice-pack button starts it via pack\launcher.py.
setlocal
cd /d "%~dp0"

rem Point this at any Python 3.8+ (the bridge uses only the standard library)
set "PY=python"
if exist "%~dp0.env-python.txt" for /f "usebackq delims=" %%i in ("%~dp0.env-python.txt") do set "PY=%%i"

if not exist "%~dp0config.json" copy "%~dp0config.example.json" "%~dp0config.json" >nul

echo [bridge] starting on 127.0.0.1:8765 ...
"%PY%" "%~dp0server.py" --config "%~dp0config.json"
pause
