@echo off
setlocal EnableExtensions
REM Запуск CustomsClear: API + React в отдельных окнах.
REM Бэкенд: customs-clear\backend → http://127.0.0.1:8001
REM Фронт:  customs-clear\frontend → http://127.0.0.1:3000

set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%customs-clear\backend"
set "FRONTEND_DIR=%ROOT%customs-clear\frontend"

if not exist "%BACKEND_DIR%\app\main.py" (
  echo Backend not found: %BACKEND_DIR%
  exit /b 1
)
if not exist "%FRONTEND_DIR%\package.json" (
  echo Frontend not found: %FRONTEND_DIR%
  exit /b 1
)

start "CustomsClear API" cmd /k cd /d "%BACKEND_DIR%" ^&^& uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
start "CustomsClear UI" cmd /k cd /d "%FRONTEND_DIR%" ^&^& npm run dev

echo Backend:  http://127.0.0.1:8001
echo Frontend: http://127.0.0.1:3000
