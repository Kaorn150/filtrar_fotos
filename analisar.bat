@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "analise.json" goto checa

echo.
echo Ja existe um analise.json.
echo   [S] continuar de onde parou  --retomar
echo   [N] medir tudo de novo
echo.
choice /c SN /n /m "Continuar de onde parou? "
if errorlevel 2 goto novo
".venv\Scripts\python.exe" analisar.py --retomar %*
goto fim

:checa
:novo
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" analisar.py %*
) else (
  python analisar.py %*
)

:fim
echo.
pause
