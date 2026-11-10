@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "analise.json" (
  echo Falta o analise.json. Rode antes o analisar.bat
  echo.
  pause
  exit /b 1
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" filtrar.py %*
) else (
  python filtrar.py %*
)

echo.
pause
