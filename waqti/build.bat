@echo off
cd /d "%~dp0"
echo Installing PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (echo Python not found. Install Python from python.org first. & pause & exit /b 1)
python -m PyInstaller --onefile --noconsole --name Waqti waqti.pyw
echo.
echo Done! Your app is here: dist\Waqti.exe
pause
