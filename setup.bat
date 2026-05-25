@echo off
setlocal

cd /d "%~dp0"

echo.
echo === Video2Recipe: instalacion ===
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo Python no esta instalado o no esta en PATH.
  echo Descargalo desde https://python.org y marca "Add Python to PATH".
  pause
  exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
  echo Node.js no esta instalado o no esta en PATH.
  echo Descargalo desde https://nodejs.org
  pause
  exit /b 1
)

if not exist backend\.venv (
  echo Creando entorno virtual de Python...
  python -m venv backend\.venv
)

echo Instalando dependencias del backend...
call backend\.venv\Scripts\python.exe -m pip install --upgrade pip
call backend\.venv\Scripts\pip.exe install -r backend\requirements.txt
if errorlevel 1 (
  echo Error instalando dependencias del backend.
  pause
  exit /b 1
)

echo Instalando dependencias del frontend...
cd frontend
call npm install
if errorlevel 1 (
  echo Error instalando dependencias del frontend.
  pause
  exit /b 1
)
cd ..

if not exist .env (
  copy .env.example .env >nul
  echo Se creo .env desde .env.example. Edita GROQ_API_KEY antes de ejecutar.
)

echo.
echo Instalacion completada.
echo Edita video2recipe\.env y coloca tu GROQ_API_KEY.
pause
