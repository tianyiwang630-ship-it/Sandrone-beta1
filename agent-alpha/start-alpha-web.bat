@echo off
setlocal
chcp 65001 >nul

set "ROOT=%~dp0"
set "FRONTEND=%ROOT%frontend"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"
set "PYTHON_VERSION=3.12"

if not exist "%PYTHON%" (
  echo agent-alpha .venv was not found.
  echo Run setup-agent-alpha.ps1 first to create the uv-managed environment.
  pause
  exit /b 1
)

set "VERSION_FILE=%TEMP%\agent-alpha-python-version-%RANDOM%.txt"
"%PYTHON%" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" > "%VERSION_FILE%"
if errorlevel 1 (
  echo Failed to inspect agent-alpha .venv Python version.
  del "%VERSION_FILE%" >nul 2>nul
  pause
  exit /b 1
)
set /p ACTUAL_PYTHON_VERSION=<"%VERSION_FILE%"
del "%VERSION_FILE%" >nul 2>nul
if not "%ACTUAL_PYTHON_VERSION%"=="%PYTHON_VERSION%" (
  echo agent-alpha .venv is Python %ACTUAL_PYTHON_VERSION%, but Python %PYTHON_VERSION% is required.
  echo Remove .venv and run setup-agent-alpha.ps1 again.
  pause
  exit /b 1
)

if not exist "%FRONTEND%\node_modules" (
  echo Installing frontend dependencies...
  pushd "%FRONTEND%"
  call npm.cmd install
  if errorlevel 1 (
    popd
    pause
    exit /b 1
  )
  popd
)

for %%P in (8787 5173) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr /R /C:":%%P .*LISTENING"') do (
    if not "%%A"=="0" (
      echo Stopping old agent-alpha service on port %%P, pid %%A
      taskkill /PID %%A /F >nul 2>nul
    )
  )
)

start "agent-alpha api" /D "%ROOT%" cmd /k ""%PYTHON%" -m agent.server.app"
start "agent-alpha frontend" /D "%FRONTEND%" cmd /k "npm.cmd run dev"

timeout /t 3 >nul
start "" "http://127.0.0.1:5173"
