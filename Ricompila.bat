@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo Ricompila IWAU-ITA-Installer.exe con PyInstaller.
echo Richiede: python 3 + "pip install pyinstaller"
echo.
python -m PyInstaller --onefile --windowed --name "IWAU-ITA-Installer" ^
  --version-file "%~dp0version_info.txt" ^
  --distpath "%~dp0" --workpath "%~dp0build" --specpath "%~dp0build" ^
  "%~dp0installer_ita.py"
echo.
pause
