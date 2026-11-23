@echo off
rem Instala TALOS: entorno de Python, librerias, voz e IA.
cd /d "%~dp0.."
echo [1/4] Creando el entorno de Python...
if not exist venv py -3.12 -m venv venv
echo [2/4] Instalando librerias...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
echo [3/4] Descargando la voz (Alan, ingles britanico)...
set VOZ=https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx
if not exist en_GB-alan-medium.onnx powershell -NoProfile -Command "Invoke-WebRequest %VOZ% -OutFile en_GB-alan-medium.onnx"
if not exist en_GB-alan-medium.onnx.json powershell -NoProfile -Command "Invoke-WebRequest %VOZ%.json -OutFile en_GB-alan-medium.onnx.json"
echo [4/4] Descargando la IA (unos 17 GB)...
ollama pull gemma4:26b-a4b
if not exist ajustes_locales.py copy ajustes_locales.example.py ajustes_locales.py >nul
echo.
echo Listo. Abre TALOS con scripts\talos.bat
pause
