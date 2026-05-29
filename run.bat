@echo off
setlocal

cd /d "%~dp0"

:: 1. Verificar dependencias del backend
if not exist "backend\.venv\Scripts\python.exe" (
  echo ERROR: No existe el entorno virtual de Python en backend\.venv.
  echo Ejecuta setup.bat primero para instalar todas las dependencias.
  echo.
  pause
  exit /b 1
)

:: 2. Verificar dependencias del frontend
if not exist "frontend\node_modules" (
  echo ERROR: No existen las dependencias de Node.js en frontend\node_modules.
  echo Ejecuta setup.bat primero para instalar todas las dependencias.
  echo.
  pause
  exit /b 1
)

:: 3. Verificar existencia del archivo .env
if not exist .env (
  if exist .env.example (
    copy .env.example .env >nul
    echo Se ha creado el archivo .env a partir de .env.example.
    echo Por favor, abre el archivo .env y configura tu GROQ_API_KEY.
    echo.
  ) else (
    echo ERROR: No existe el archivo .env ni .env.example.
    echo Crea un archivo .env en la raiz con: GROQ_API_KEY=tu_clave
    echo.
  )
  pause
  exit /b 1
)

:: 4. Intentar iniciar MySQL local si esta instalado y el puerto 3306 no responde
powershell -NoProfile -Command "if (-not (Get-NetTCPConnection -LocalPort 3306 -ErrorAction SilentlyContinue)) { exit 1 }"
if errorlevel 1 (
  if exist "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe" (
    if exist "C:\ProgramData\MySQL\MySQL Server 8.0\my.ini" (
      echo Iniciando MySQL local en el puerto 3306 ...
      start "Ratatouille MySQL" /min "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe" --defaults-file="C:\ProgramData\MySQL\MySQL Server 8.0\my.ini"
      timeout /t 5 /nobreak >nul
    )
  )
)

:: 5. Cargar y verificar GROQ_API_KEY de forma segura (evita \r de line endings estilo Unix/Windows)
set "MY_GROQ_KEY="
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
  if "%%A"=="GROQ_API_KEY" (
    for /f "delims=" %%I in ("%%B") do set "MY_GROQ_KEY=%%I"
  )
)

:: Quitar comillas si existieran en el valor
if defined MY_GROQ_KEY (
  set "MY_GROQ_KEY=%MY_GROQ_KEY:"=%"
)

:: Si esta vacia o contiene el valor por defecto, pedirla
if "%MY_GROQ_KEY%"=="" set "MY_GROQ_KEY=tu_api_key_aqui"
if "%MY_GROQ_KEY%"=="tu_api_key_aqui" (
  echo Falta configurar la API Key de Groq.
  echo Edita el archivo .env en la raiz de la aplicacion o introducela ahora.
  echo.
  set /p MY_GROQ_KEY=Introduce tu GROQ_API_KEY para esta sesion: 
  echo.
)

:: Guardar en el entorno local de forma limpia
set "GROQ_API_KEY=%MY_GROQ_KEY%"

echo Iniciando backend en http://localhost:8000 ...
start "Video2Recipe Backend" /D "%~dp0backend" cmd /k "set GROQ_API_KEY=%GROQ_API_KEY%&& .venv\Scripts\python.exe -B -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

echo Iniciando frontend en http://localhost:5173 ...
start "Video2Recipe Frontend" /D "%~dp0frontend" cmd /k "npm run dev -- --host 0.0.0.0 --port 5173"

echo.
echo ==================================================
echo Listo:
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:5173
echo ==================================================
echo.
pause
