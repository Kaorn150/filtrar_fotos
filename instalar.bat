@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo === Instalando as dependencias (OpenCV + NumPy) ===
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo NAO achei o Python instalado.
  echo Baixe em https://www.python.org/downloads/ e marque "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente virtual...
  python -m venv .venv
)

echo Instalando pacotes...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo.
echo === Teste rapido (30 fotos) ===
".venv\Scripts\python.exe" analisar.py --limite 30 --debug 10

echo.
echo Se apareceu uma tabela de distribuicao acima, esta tudo certo.
echo Abra a pasta "debug" para ver como a faixa de cabelo foi medida.
echo.
pause
