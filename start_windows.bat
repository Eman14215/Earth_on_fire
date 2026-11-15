@echo off
cd /d "%~dp0"
python --version
if errorlevel 1 (echo Install Python 3.10+ and Add Python to PATH. & pause & exit /b 1)
python -m pip install -r requirements.txt
if errorlevel 1 (echo Dependency installation failed. & pause & exit /b 1)
start "" cmd /c "timeout /t 4 /nobreak >nul && start http://127.0.0.1:8000"
python -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
