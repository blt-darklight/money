@echo off
chcp 65001 >nul
title Daily PnL Tracker
cd /d %~dp0

rem Path to the Python interpreter that has the dependencies installed.
rem If you move this project to another PC, install deps first (see README.md),
rem then edit the line below to point to that Python.
set "PY=C:\Users\walnut\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

if not exist "%PY%" (
    echo [X] Python interpreter not found: %PY%
    echo     Please read README.md to install dependencies,
    echo     then edit the PY path in this file.
    pause
    exit /b 1
)

echo Starting Daily PnL Tracker...
rem Patch the Streamlit frontend for old mobile browsers. Idempotent:
rem re-runs automatically after a Streamlit reinstall or upgrade.
"%PY%" "%~dp0patch_streamlit.py"
echo   Browser : http://localhost:8501
echo   Phone   : http://YOUR-PC-IP:8501   (run "ipconfig" on this PC to find the IP)
echo Close this window to stop the app.
"%PY%" -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
pause
