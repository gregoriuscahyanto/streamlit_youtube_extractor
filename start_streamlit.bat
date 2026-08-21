@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv nicht gefunden.
    echo.
    echo Einmalig ausfuehren:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo Starting streamlit_youtube_extractor...
echo http://localhost:8501
echo.

".venv\Scripts\python.exe" -m streamlit run app.py

if errorlevel 1 (
    echo.
    echo [ERROR] Streamlit wurde mit einem Fehler beendet.
    pause
)

endlocal
