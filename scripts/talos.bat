@echo off
rem Abre TALOS. Arranca Ollama si no esta corriendo.
cd /d "%~dp0.."
tasklist | find /i "ollama.exe" >nul || start "" /min ollama serve
timeout /t 3 >nul
call venv\Scripts\activate
python talos.py
pause
