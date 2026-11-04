@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m engine.cli quick samples\sample_script.txt --title "Water Cycle"
pause
