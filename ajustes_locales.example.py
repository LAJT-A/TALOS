"""Ajustes personales de TALOS.

Copia este archivo como ajustes_locales.py y cambia lo que quieras: lo que pongas aquí
reemplaza al valor que trae talos.py. ajustes_locales.py no se sube a GitHub.
"""

# Número del micrófono. Para ver la lista:
#   python -c "import sounddevice as sd; print(sd.query_devices())"
MIC_INDEX = 1

# Apodos para WhatsApp: como le dices tú -> como está guardado el chat.
NICKNAMES = {
    "mi hermano": "Carlos Pérez",
}

# Lo que TALOS y el bot saben de ti (apodos, como se llama tu casa...).
OWNER_INFO = ""

# Tu nombre, para el bot de WhatsApp ("Soy la IA de ...").
OWNER_NAME = ""

# Todos tus nombres y apodos: el bot nunca te insulta con ninguno (y tampoco dice "no tengo permitido").
OWNER_ALIASES = []

# Prefijo de país para números guardados sin "+".
COUNTRY_CODE = "58"

# App que abre la "noche de juegos".
GAME_NIGHT_APP = "Rocket League"
