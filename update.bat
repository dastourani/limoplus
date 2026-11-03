@echo off
rem LimooKhan: update the laptop server and the web version of the app, then start the server.
rem Double-click this file. It never touches .env, db.sqlite3, media or venv.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo [1/5] Getting the latest changes from GitHub...
git pull --ff-only
if errorlevel 1 (
  echo.
  echo *** Could not get the changes. Check the internet connection, then try again.
  pause
  exit /b 1
)

echo.
echo [2/5] Getting the latest web version of the app...
git fetch -q origin web-build
if errorlevel 1 (
  echo     No web version yet - skipped. The server still runs.
) else (
  if exist backend\webapp rmdir /s /q backend\webapp
  mkdir backend\webapp
  git archive --format=zip -o "%TEMP%\limookhan-web.zip" origin/web-build
  tar -xf "%TEMP%\limookhan-web.zip" -C backend\webapp
  del "%TEMP%\limookhan-web.zip"
)

cd backend
if not exist venv (
  echo.
  echo     Making the Python environment ^(first time only^)...
  python -m venv venv
)
call venv\Scripts\activate.bat

echo.
echo [3/5] Checking Python packages...
pip install -q --disable-pip-version-check --timeout 15 --retries 1 -r requirements.txt
if errorlevel 1 echo     Could not reach the package server - continuing with the packages already installed.

echo.
echo [4/5] Updating the database...
python manage.py migrate
if errorlevel 1 (
  echo.
  echo *** The database update failed. Send a photo of this window.
  pause
  exit /b 1
)

echo.
echo [5/5] Starting the server. The app in a browser:  http://localhost:8000/
echo       Panel:  http://localhost:8000/admin/      Stop the server: Ctrl+C
echo.
python manage.py runserver 0.0.0.0:8000
pause