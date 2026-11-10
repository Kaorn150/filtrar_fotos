@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" comparar_pastas.py %*
) else (
  python comparar_pastas.py %*
)

echo.
pause
