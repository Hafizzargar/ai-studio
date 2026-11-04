@echo off
cd /d "%~dp0"
where python >nul 2>nul || (echo Python not found. Install Python 3.11 or 3.12 and tick "Add to PATH". & pause & exit /b 1)
python -m venv .venv || (echo Could not create virtual environment & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || (echo Install failed & pause & exit /b 1)
echo.
echo Done. Next: put ffmpeg.exe in the vendor folder (or run scripts\download_tools.ps1), then run run_ui.bat
python -m engine.cli doctor
pause
