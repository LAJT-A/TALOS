"""TALOS: asistente de voz para Windows.

Escucha con Google (entiende español e inglés), responde en inglés con la voz de Alan
y razona con una IA local en Ollama. Los ajustes están aquí arriba; los personales
van en ajustes_locales.py (ver ajustes_locales.example.py).
"""
import asyncio
import base64
import collections
import datetime
import difflib
import hashlib
import io
import json
import os
import queue
import re
import subprocess
import threading
import time
import wave
import webbrowser
import winsound
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import quote, quote_plus

import numpy as np
import ollama
import pyautogui
import pyperclip
import sounddevice as sd
import speech_recognition as sr
from piper import PiperVoice

import comandos
import telefono
import whatsapp
import ui

# ======================= AJUSTES =======================
MIC_INDEX = 1
LANGUAGES = ("en-US", "es-VE")   # Google escucha en los dos a la vez y se queda con el mejor
WAKE_ENABLED = True              # escuchar siempre la palabra "Jarvis" o "Talos"
GOOGLE_TIMEOUT = 6               # segundos maximos esperando a Google
WAKE_WORDS = ("jarvis", "jarves", "jarvas", "jarvish", "travis", "yarvis", "harvis", "jarviz",
              "garvis", "jarbi", "jarvi", "jarvez", "yarbi", "harvey's", "jarvis's",
              "jarbis", "yarbis", "jervis", "charvis",
              # tambien responde a "Talos" (sin parecidos sueltos: "que tal" no lo debe despertar)
              "talos", "thalos", "tallos", "talus", "telos", "tālos", "talo's", "taloss")
FOLLOW_UP_SECONDS = 8            # tras responder, sigue escuchando sin que lo actives
END_WORDS = r"^(thanks|thank you|that's all|that is all|never mind|nevermind|gracias|eso es todo|nada mas|ya esta|listo)$"

PHONE_ENABLED = True             # hablarle a Jarvis desde el celular por Bluetooth
PHONE_PORT = ""                  # puerto COM entrante de Bluetooth; vacio = lo busca solo
WHATSAPP_FROM_PC = True          # enviar los WhatsApp con WhatsApp de escritorio (False: desde el telefono)
WHATSAPP_USE_CONTACTS = False    # True: si no encuentra el chat en WhatsApp, pide el numero a los contactos del telefono
WHATSAPP_WAIT = 4                # segundos que tarda WhatsApp de escritorio en abrir el chat
COUNTRY_CODE = "58"              # prefijo para los contactos guardados sin codigo de pais
# Apodos: como le dices tú -> como está guardado el chat en WhatsApp. Un trozo del nombre ya
# funciona solo ("pepe" encuentra "Pepe Trueno"); esto es para nombres que no se parecen en nada.
NICKNAMES = {}
WHATSAPP_DIRECT = True           # WhatsApp directo con neonize (si falla, usa la ventana de escritorio)
WHATSAPP_ANNOUNCE = True         # avisar por las bocinas cuando llega un WhatsApp (solo dice de quien)
PHONE_ALOUD = False              # True: lo que pidas desde el celular tambien se responde por las bocinas

CLAP_ENABLED = True
CLAP_LEVEL = 0.20                # si no detecta tus aplausos, bajalo; si se activa solo, subelo
MIN_VOICE = 0.005                # volumen minimo que cuenta como voz
SILENCE_END = 0.7                # segundos de silencio para terminar la frase
MAX_SPEECH = 10                  # duracion maxima de una frase, en segundos
STOP_LEVEL = 0.012               # si no te oye mientras habla, bajalo
STOP_WORDS = r"\b(stop|para|parate|detente|callate|basta)\b"

MODEL = "gemma4:26b-a4b"         # IA para preguntas y para mirar la pantalla
KEEP_ALIVE = "15m"               # minutos que la IA queda en memoria tras usarla
VOICE = "en_GB-alan-medium.onnx"
GREETING = "Yes sir?"
SCREEN_MEMORY = 120              # segundos que recuerda la ultima captura para seguir preguntando
SPOTIFY_STEP = 0.15              # cuanto sube o baja el volumen de Spotify cada vez
SPOTIFY_WAIT = 3                 # segundos que espera a que Spotify muestre la busqueda

GAME_NIGHT_APP = "Rocket League"
# Modo gamer: procesos que se cierran, por el inicio de su nombre.
GAMER_CLOSE = ("lively", "copilot", "m365copilot", "widgets", "widgetservice",
               "phoneexperiencehost", "crossdeviceservice", "yourphone",
               "ms-teams", "teams", "onedrive", "cortana",
               "msedge", "whatsapp", "olk", "outlook")
# Nunca se cierran, aunque coincidan con la lista anterior.
GAMER_KEEP = ("dnplayer", "ldplayer", "ld9", "ldvbox", "ldmulti", "vbox",
              "python", "ollama", "claude", "explorer", "msedgewebview", "spotify")
# =======================================================

try:  # ajustes personales (apodos, micrófono...) que no se suben a GitHub
    from ajustes_locales import *  # noqa: F401,F403
except ImportError:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SHOT_DIR = os.path.join(HERE, "screenshots")
TTS_FILE = os.path.join(HERE, "tts.wav")
BLOCK = 0.03                     # segundos por bloque de audio
NO_WINDOW = 0x08000000

VISION_PROMPT = ("The user's message includes a screenshot of their screen taken a moment ago. "
                 "You can see it: use it to answer, describing what is on screen when asked.")
# Ordenes que la IA puede usar por su cuenta (escribe "DO: <orden>")
ACTION_LIST = """open <app name, website or folder: downloads, documents, desktop, pictures, music, videos>
close <app name>
find <photo|video|song|document|file> <optional words of its name> in <folder>   (you get back the newest matches)
open file <number from the list you got back, or part of the file name>
play <song, artist or genre> on spotify
play <video> on youtube
pause music | resume music | next song | previous song | what is playing
spotify volume up | spotify volume down | spotify volume <0-100> | mute spotify | unmute spotify
volume up | volume down | mute
search <text to search on Google>
type <text to write in the current window>
press <keys, e.g. ctrl c, alt tab, enter>
click <visible button text> | double click <text> | right click <text>
scroll up | scroll down | switch to <window name>
new tab | close tab | close window | minimize | maximize | show desktop
screenshot
timer <number> <second|minute|hour>
note <text to save>
active gamer mode | active game night
answer call | end call   (calls on the user's phone)
phone pause music | phone resume music | phone next song | phone previous song | phone play <song or artist>   (search and play it on the phone)
whatsapp audio to <name>: <what to say>   (sends a WhatsApp VOICE message spoken with your own voice; use it when the user asks for an audio, voice note or "nota de voz". Write what to say in English unless the user asks for another language, because your voice is English)
read messages   (reads the latest WhatsApp messages out loud)
whatsapp reply to <name>: <message>   (sends a WhatsApp to that contact, also to start a chat; <name> is a person or a group, as named in WhatsApp; a nickname or part of the name works; write the message exactly as the user wants it sent, in the user's own language, never translated)
phone volume up | phone volume down | phone volume <0-100>   (music playing on the phone; use the number when the user gives a percentage)"""

SYSTEM_PROMPT = ("You are Jarvis, also called Talos, a helpful voice assistant on the user's Windows PC. "
                 "The user may speak Spanish or English, but always reply in English. "
                 "Your replies are read aloud: use plain text, no markdown, lists or emojis, "
                 "and keep them to at most three short sentences unless asked for more. "
                 "You can control the user's PC yourself. To do something, write one line per action that "
                 "starts with DO: followed by one of these commands, in this exact English form:\n"
                 + ACTION_LIST +
                 "\nYou may chain several DO: lines in order, for example 'DO: open notepad' then "
                 "'DO: type hello'. When you act, write only the DO: lines, nothing else. "
                 "Work out what the user means even if they say it in Spanish, vaguely, or the speech "
                 "recognizer misheard a name (for example 'si es 1.6' can be the game 'CS 1.6'). "
                 "After your DO: lines the PC answers with RESULTS. If something FAILED, reason about what "
                 "the user really wanted and try again with a better command, using the exact app or file "
                 "names RESULTS gives you. Only say something was done when RESULTS says OK; never pretend. "
                 "The user never has to use exact words: 'pasa la musica en el cel' means phone next song, "
                 "'atiende', 'dale, agarrala' or 'si' while the phone rings mean answer call, 'ahorita no' means "
                 "end call. When they mention their phone, cel, celular or telefono, use the phone commands. "
                 "For WhatsApp: if the user dictates the exact words ('dile a Ana que ya voy'), send exactly those "
                 "words ('Ya voy'); if they describe what to say ('saludala y bromea un poco'), write the message "
                 "yourself. A group is addressed by its name just like a person. "
                 "Answer questions from your own knowledge; use 'search' only when the user asks to look "
                 "something up on the web. If nothing on the list can do it, say so briefly.")

APPS = {"chrome": "chrome", "calculator": "calc", "calculadora": "calc", "notepad": "notepad",
        "note pad": "notepad", "bloc de notas": "notepad", "navegador": "chrome",
        "vs code": "code", "paint": "mspaint", "spotify": "spotify:"}
# Frases que hacen que Jarvis mire la pantalla (sin acentos)
LOOK_VERBS = r"\b(ve|velo|mira|miralo|analiza|revisa|dime|look|check|tell|what|que)\b"
SCREEN_WORDS = (r"pantalla|\bscreen\b|que estoy haciendo|que hago|what am i doing|what i'm doing|que ves"
                r"|what do you see|\bvelo\b|\bmiralo\b|mira esto|look at|lee esto|read this|explica esto"
                r"|explain this|que es esto|what is this|what's this|que (aplicacion|app|ventana)|which (app|window)"
                r"|detras de|behind|what's on|what is on|que hay (en|abajo|arriba|detras)"
                r"|(captura|screenshot).*\b(ve|velo|mira|miralo|analiza|revisa|dime|look|check|tell)\b"
                r"|(revisa|analiza|mira) (la|el) (captura|screenshot)")
SHORTCUTS = {"copy": ("ctrl", "c"), "paste": ("ctrl", "v"), "cut": ("ctrl", "x"),
             "select all": ("ctrl", "a"), "undo": ("ctrl", "z"), "redo": ("ctrl", "y"),
             "save": ("ctrl", "s"), "find": ("ctrl", "f"), "new tab": ("ctrl", "t"),
             "close tab": ("ctrl", "w"), "next tab": ("ctrl", "tab"), "refresh": ("f5",),
             "go back": ("alt", "left"), "switch window": ("alt", "tab"),
             "show desktop": ("win", "d"), "minimize": ("win", "down"), "maximize": ("win", "up")}
KEYMAP = {"control": "ctrl", "windows": "win", "escape": "esc", "return": "enter",
          "page up": "pageup", "page down": "pagedown"}

S = {"state": "sleep", "text": ""}   # lo comparte la interfaz
events = queue.Queue()               # clic o aplausos
voice = PiperVoice.load(os.path.join(HERE, VOICE))
recognizer = sr.Recognizer()
recognizer.operation_timeout = GOOGLE_TIMEOUT
pool = ThreadPoolExecutor(max_workers=4)
history = []
APP_DISPLAY = {}     # nombre en minusculas -> nombre tal como se ve (para el menu de la app)
ICON_DIR = os.path.join(HERE, "iconos")
AUDIO_DIR = os.path.join(HERE, "audios")              # audios que Jarvis graba para mandar por WhatsApp
CONTACTS_FILE = os.path.join(HERE, "contactos.json")  # numeros que ya busco en el telefono
DESKTOP_NAMES = {}   # nombre legible del acceso directo -> ruta
APP_ALIASES = {}     # siglas -> nombre de la app
LAST_FILES = []      # ultima lista de archivos que encontro "find"
wa_messages = collections.deque(maxlen=8)  # (quien, mensaje, hora) de los ultimos WhatsApp
phone_state = {"call": None, "who": ""}  # None, "ringing" o "active"
agent = {"on": False, "fails": [], "info": []}  # resultados de las ordenes que pide la IA
FOLDERS = {"downloads": "Downloads", "descargas": "Downloads", "documents": "Documents",
           "documentos": "Documents", "desktop": "Desktop", "escritorio": "Desktop",
           "pictures": "Pictures", "imagenes": "Pictures", "fotos": "Pictures", "photos": "Pictures",
           "music": "Music", "musica": "Music", "videos": "Videos"}
FILE_KINDS = {"image": (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"),
              "video": (".mp4", ".mkv", ".mov", ".avi", ".webm"),
              "audio": (".mp3", ".wav", ".flac", ".m4a", ".ogg"),
              "document": (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".txt", ".csv")}
KIND_WORDS = {**{w: "image" for w in ("photo", "photos", "foto", "fotos", "image", "images", "imagen",
                                      "imagenes", "picture", "pictures")},
              **{w: "video" for w in ("video", "videos")},
              **{w: "audio" for w in ("song", "songs", "audio", "audios", "cancion", "canciones")},
              **{w: "document" for w in ("document", "documents", "documento", "documentos")}}
FILE_STOP = {"file", "files", "archivo", "archivos", "named", "called", "a", "an", "the", "any", "some",
             "recent", "latest", "last", "newest", "my", "mi", "mis", "un", "una", "el", "la", "de", "of"}
FAIL_TEXT = r"I could not find(?! a WhatsApp)|I do not know that key"


def set_state(state, text=""):
    S["state"], S["text"] = state, text


# ======================= APPS =======================
START_APPS = {}
DESKTOP_APPS = {}


def _norm(name):
    name = name.lower().replace("acceso directo", "").replace("shortcut", "")
    return re.sub(r"[^a-z0-9]", "", name)


def load_apps():
    """Lee el menu Inicio y los accesos directos del escritorio."""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json"],
                             capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW).stdout
        data = json.loads(out)
        for app in data if isinstance(data, list) else [data]:
            START_APPS[app["Name"].lower()] = app["AppID"]
            APP_DISPLAY[app["Name"].lower()] = app["Name"]
    except Exception as e:
        print("Menu Inicio:", e)
    folders = {os.path.join(os.path.expanduser("~"), "Desktop")}
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "[Environment]::GetFolderPath('Desktop');"
                              "[Environment]::GetFolderPath('CommonDesktopDirectory')"],
                             capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW).stdout
        folders.update(line.strip() for line in out.splitlines() if line.strip())
    except Exception as e:
        print("Escritorio:", e)
    for folder in folders:
        if os.path.isdir(folder):
            for item in os.listdir(folder):
                stem, ext = os.path.splitext(item)
                if ext.lower() in (".lnk", ".url", ".exe", ".appref-ms"):
                    DESKTOP_APPS[_norm(stem)] = os.path.join(folder, item)
                    clean_name = re.sub(r"\s*-?\s*(acceso directo|shortcut)", "", stem, flags=re.I).strip().lower()
                    DESKTOP_NAMES[clean_name] = os.path.join(folder, item)
                    APP_DISPLAY[clean_name] = re.sub(r"\s*-?\s*(acceso directo|shortcut)", "", stem, flags=re.I).strip()
    build_aliases()
    print(f"Apps: {len(DESKTOP_APPS)} en el escritorio, {len(START_APPS)} en Inicio")
    make_icons()


def icon_key(name):
    """Nombre del archivo del logo de una app. La app del telefono hace el mismo calculo."""
    return hashlib.md5(name.lower().encode("utf-8")).hexdigest()[:12]


def make_icons():
    """Guarda en la carpeta "iconos" el logo de cada app, para el menu del telefono."""
    try:
        os.makedirs(ICON_DIR, exist_ok=True)
        items = []
        for low, shown in APP_DISPLAY.items():
            path = DESKTOP_NAMES.get(low) or ("shell:AppsFolder\\" + START_APPS[low] if low in START_APPS else None)
            if path and not os.path.exists(os.path.join(ICON_DIR, icon_key(shown) + ".png")):
                items.append({"key": icon_key(shown), "path": path})
        if not items:
            return
        list_file = os.path.join(ICON_DIR, "_lista.json")
        with open(list_file, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                              os.path.join(HERE, "scripts", "iconos.ps1"), list_file, ICON_DIR],
                             capture_output=True, text=True, timeout=600, creationflags=NO_WINDOW)
        print("Logos de apps:", (out.stdout.strip() or out.stderr.strip()[:300] or "sin respuesta"))
    except Exception as e:
        print("Logos de apps:", e)


def send_icons(keys):
    """Manda al telefono los logos que pidio, sin trabar el resto de la conversacion."""
    sent = 0
    for key in keys:
        path = os.path.join(ICON_DIR, key + ".png")
        if re.fullmatch(r"[0-9a-f]{12}", key) and os.path.exists(path):
            with open(path, "rb") as f:
                if not telefono.send(f"#ICON {key} " + base64.b64encode(f.read()).decode("ascii")):
                    break
            sent += 1
            time.sleep(0.03)
    print(f"Logos enviados al celular: {sent} de {len(keys)}")


def _aliases(name):
    """"visual studio code" -> vscode, vsc; "mortal kombat 11" -> mk11; "counter-strike 1.6" -> cs16."""
    words = re.findall(r"[a-z]+|\d+", name.lower())
    out = set()
    for k in range(2, len(words) + 1):
        alias = "".join(w if w.isdigit() else w[0] for w in words[:k]) + "".join(words[k:])
        if len(alias) >= 3:
            out.add(alias)
    return out


def build_aliases():
    for name in list(START_APPS) + list(DESKTOP_NAMES):
        for alias in _aliases(name):
            APP_ALIASES.setdefault(alias, name)


def folder_path(name):
    """Ruta de una carpeta del usuario ("descargas", "mis documentos"...) o None."""
    key = comandos._strip(name.lower()).strip()
    key = re.sub(r"^(the |my |mi |mis |la |el |las |los )?(folder |carpeta )?(de |of )?(the |my |mi |mis )?", "", key)
    key = re.sub(r" folder$", "", key).strip()
    home = os.path.expanduser("~")
    if key in FOLDERS:
        for base in (home, os.path.join(home, "OneDrive")):
            path = os.path.join(base, FOLDERS[key])
            if os.path.isdir(path):
                return path
    path = os.path.expanduser(name.strip())
    return path if os.path.isabs(path) and len(path) > 3 and os.path.isdir(path) else None


def find_files(what, folder=None):
    """Archivos mas recientes que coinciden con "what" (tipo y palabras del nombre)."""
    roots = [folder_path(folder)] if folder else [folder_path(f) for f in
                                                    ("downloads", "desktop", "documents", "pictures", "videos", "music")]
    roots = [r for r in roots if r]
    exts, words = set(), []
    for w in re.findall(r"[a-z0-9]+", comandos._strip(what.lower())):
        if w in KIND_WORDS:
            exts.update(FILE_KINDS[KIND_WORDS[w]])
        elif w in ("pdf", "png", "jpg", "mp3", "mp4", "docx", "xlsx", "pptx", "txt", "zip", "exe"):
            exts.add("." + w)
        elif w not in FILE_STOP:
            words.append(w)
    found, seen = [], 0
    for root in roots:
        depth0 = root.rstrip("\\/").count(os.sep)
        for folder_now, dirs, files in os.walk(root):
            if folder_now.count(os.sep) - depth0 >= 3:
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith((".", "$")) and d.lower() not in ("appdata", "node_modules")]
            for name in files:
                seen += 1
                low = comandos._strip(name.lower())
                if (not exts or low.endswith(tuple(exts))) and all(w in low for w in words):
                    path = os.path.join(folder_now, name)
                    try:
                        found.append((os.path.getmtime(path), path))
                    except OSError:
                        pass
            if seen > 50000:
                break
    found.sort(reverse=True)
    LAST_FILES[:] = [path for _, path in found[:6]]
    return found[:6]


def pick_file(target):
    """Archivo de la ultima lista (por numero o nombre) o, si no, lo busca."""
    target = target.strip()
    numbers = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "first": 1, "second": 2, "third": 3}
    n = int(target) if target.isdigit() else numbers.get(target.replace("number ", ""))
    if n and 0 < n <= len(LAST_FILES):
        return LAST_FILES[n - 1]
    if os.path.isfile(os.path.expanduser(target)):
        return os.path.expanduser(target)
    low = comandos._strip(target.lower())
    for path in LAST_FILES:
        if low in comandos._strip(os.path.basename(path).lower()):
            return path
    found = find_files(target)
    return found[0][1] if found else None


def app_hint(name):
    """Nombres de apps para que la IA elija la que quisiste decir."""
    desktop = sorted(DESKTOP_NAMES)
    target = _norm(name)
    start = sorted(START_APPS, key=lambda k: -difflib.SequenceMatcher(None, target, _norm(k)).ratio())[:30]
    return ("Apps on the desktop: " + "; ".join(desktop) + ". Other installed apps with similar names: "
            + "; ".join(start) + ". Folders: downloads, documents, desktop, pictures, music, videos. "
            "Pick the one the user means and use that exact name.")


def _best_match(name, keys):
    if not name or not keys:
        return None
    if name in keys:
        return name
    partial = [k for k in keys if name in k or (len(k) >= 4 and k in name)]
    if partial:
        return min(partial, key=len)
    close = difflib.get_close_matches(name, list(keys), n=1, cutoff=0.7)
    return close[0] if close else None


def find_desktop_app(name):
    key = _best_match(_norm(name), DESKTOP_APPS)
    return DESKTOP_APPS[key] if key else None


def open_app(name):
    """Abre por este orden: atajos conocidos, escritorio y menu Inicio."""
    if name in ("youtube", "google"):
        webbrowser.open(f"https://{name}.com")
        return name
    if name in APPS:
        os.startfile(APPS[name]) if APPS[name].endswith(":") else os.system(f"start {APPS[name]}")
        return name
    folder = folder_path(name)
    if folder:
        os.startfile(folder)
        return os.path.basename(folder) + " folder"
    shortcut = find_desktop_app(name)
    if shortcut:
        os.startfile(shortcut)
        return name
    spaced = {k.replace(" ", ""): k for k in START_APPS}
    key = _best_match(name.replace(" ", ""), spaced)
    if key:
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + START_APPS[spaced[key]]])
        return spaced[key]
    full = APP_ALIASES.get(_norm(name))  # "vscode" = visual studio code, "mk11" = mortal kombat 11
    if full in DESKTOP_NAMES:
        os.startfile(DESKTOP_NAMES[full])
        return full
    if full in START_APPS:
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + START_APPS[full]])
        return full
    return None


CLOSE_NEVER = ("python", "ollama", "explorer", "claude", "svchost", "csrss", "winlogon", "dwm",
               "system", "conhost", "windowsterminal", "cmd", "taskmgr")


def close_app(name):
    """Cierra un programa por su nombre o por el titulo de su ventana. Devuelve lo que cerro."""
    target = _norm(name).replace(" ", "")
    if not target:
        return None
    try:
        out = subprocess.run(["tasklist", "/V", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             timeout=20, creationflags=NO_WINDOW).stdout
    except Exception as e:
        print("Cerrar:", e)
        return None
    by_exe, by_title = set(), set()
    for line in out.splitlines():
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) < 2:
            continue
        exe = cols[0]
        stem = exe.lower().removesuffix(".exe")
        if stem.startswith(CLOSE_NEVER):
            continue
        title = _norm(cols[-1]).replace(" ", "") if cols[-1] not in ("N/A", "") else ""
        if target in stem or (len(stem) >= 4 and stem in target):
            by_exe.add(exe)
        elif title and target in title:
            by_title.add(exe)
    found = by_exe or by_title
    if not found:
        return None
    for exe in found:  # primero le pide que se cierre; si no, lo fuerza
        subprocess.run(["taskkill", "/T", "/IM", exe], capture_output=True, timeout=20, creationflags=NO_WINDOW)
    time.sleep(2)
    for exe in found:
        subprocess.run(["taskkill", "/F", "/T", "/IM", exe], capture_output=True, timeout=20, creationflags=NO_WINDOW)
    print("Cerrado:", ", ".join(sorted(found)))
    return name


# ======================= MODOS DE JUEGO =======================
def gamer_mode():
    """Cierra lo de GAMER_CLOSE (nunca lo de GAMER_KEEP) y libera la IA de la memoria."""
    try:
        ollama.generate(model=MODEL, prompt="", keep_alive=0)
    except Exception:
        pass
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             timeout=20, creationflags=NO_WINDOW).stdout
    except Exception as e:
        print("Modo gamer:", e)
        return 0
    running = {line.split('","')[0].strip('" ') for line in out.splitlines() if line.strip()}
    closed = []
    for proc in sorted(running):
        low = proc.lower()
        if low.startswith(GAMER_KEEP) or not low.startswith(GAMER_CLOSE):
            continue
        done = subprocess.run(["taskkill", "/F", "/T", "/IM", proc], capture_output=True,
                              timeout=20, creationflags=NO_WINDOW)
        if done.returncode == 0:
            closed.append(proc)
    print("Modo gamer, cerrados:", ", ".join(closed) or "ninguno")
    return len(closed)


# ======================= SPOTIFY =======================
def spotify_volumes():
    """Controles de volumen propios de Spotify en el mezclador de Windows."""
    from pycaw.pycaw import AudioUtilities
    return [s.SimpleAudioVolume for s in AudioUtilities.GetAllSessions()
            if s.Process and s.Process.name().lower() == "spotify.exe"]


def spotify_volume(change=None, level=None, mute=None):
    """Devuelve el volumen nuevo en %, o None si Spotify no esta sonando."""
    controls = spotify_volumes()
    if not controls:
        return None
    new = level if level is not None else controls[0].GetMasterVolume() + (change or 0)
    new = max(0.0, min(1.0, new))
    for c in controls:
        if mute is not None:
            c.SetMute(int(mute), None)
        else:
            c.SetMute(0, None)
            c.SetMasterVolume(new, None)
    return round(new * 100)


def spotify_media(action):
    """Pausa, play, siguiente, anterior o info de Spotify con los controles de Windows.

    Devuelve False si Spotify no esta abierto; si falta winrt, usa las teclas multimedia.
    """
    try:
        from winrt.windows.media.control import \
            GlobalSystemMediaTransportControlsSessionManager as Manager
    except ImportError:
        keys = {"pause": "playpause", "play": "playpause", "next": "nexttrack", "previous": "prevtrack"}
        if action not in keys:
            return None
        pyautogui.press(keys[action])
        return True

    async def run():
        manager = await Manager.request_async()
        session = next((s for s in manager.get_sessions()
                        if "spotify" in (s.source_app_user_model_id or "").lower()), None)
        if session is None:
            return False
        if action == "info":
            props = await session.try_get_media_properties_async()
            return props.title, props.artist
        if action == "previous":  # pasados 3 s, Spotify reinicia la cancion en vez de volver
            try:
                pos = session.get_timeline_properties().position.total_seconds()
            except Exception:
                pos = 0
            await session.try_skip_previous_async()
            if pos > 3:
                await asyncio.sleep(0.3)
                await session.try_skip_previous_async()
            return True
        method = {"pause": "try_pause_async", "play": "try_play_async", "next": "try_skip_next_async"}[action]
        return await getattr(session, method)()

    return asyncio.run(run())


def spotify_window():
    """Ventana principal de Spotify, o None."""
    import psutil
    import win32gui
    import win32process
    found = []

    def check(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            try:
                pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                if psutil.Process(pid).name().lower() == "spotify.exe":
                    found.append(hwnd)
            except Exception:
                pass
    win32gui.EnumWindows(check, None)
    return found[0] if found else None


def find_green_button(img):
    """Centro del boton verde redondo de reproducir (el del resultado principal)."""
    rgb = np.asarray(img.convert("RGB"))[::2, ::2].astype(np.int16)  # a mitad de tamano, mas rapido
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mask = (g > 170) & (r < 90) & (b < 140) & (g - r > 110)  # verde de Spotify
    seen = np.zeros_like(mask)
    best = None
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        stack, pts = [(y, x)], []
        seen[y, x] = True
        while stack:
            cy, cx = stack.pop()
            pts.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        ys, xs = [p[0] for p in pts], [p[1] for p in pts]
        h, w = max(ys) - min(ys) + 1, max(xs) - min(xs) + 1
        fill = len(pts) / (h * w)
        if 14 <= w <= 45 and 0.8 <= w / h <= 1.25 and fill > 0.55:  # redondo, no la barra de "jam"
            center = ((min(xs) + max(xs)) + 1, (min(ys) + max(ys)) + 1)  # vuelve a tamano real
            if best is None or center[1] < best[1]:  # el mas alto de la pagina
                best = center
    return best


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]+", comandos._strip(text.lower())) if len(w) >= 3}


def _click_top_result(was_open):
    """Pone el resultado principal de la busqueda que esta en pantalla. True si pudo."""
    deadline = time.time() + (2 if was_open else 8)
    while True:
        try:
            hwnd = spotify_window()
            if hwnd:
                import win32gui
                pyautogui.press("alt")
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.4)
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                # se salta la biblioteca de la izquierda y la barra de abajo
                box = (left + (right - left) // 4, top + 60, (right - left) * 3 // 4, (bottom - top) // 2)
                spot = find_green_button(pyautogui.screenshot(region=box))
                if spot:
                    pyautogui.click(box[0] + spot[0], box[1] + spot[1])
                    return True
        except Exception as e:
            print("Spotify:", e)
        if time.time() > deadline:
            return False
        time.sleep(0.8)


def _spotify_search(text, wait):
    print("Spotify busca:", text)
    os.startfile("spotify:search:" + quote_plus(text, safe=':"'))  # Spotify usa + para los espacios
    time.sleep(wait)


def spotify_play(query):
    """Busca en Spotify y pone el resultado principal."""
    try:
        was_open = spotify_window() is not None
    except Exception:
        was_open = True
    speak(f"Looking for {query} on Spotify.")
    if not was_open:
        # Si Spotify esta cerrado, primero se abre solo y se espera a que cargue: mandarle la busqueda
        # mientras arranca hace que Windows diga "The Spotify application is not responding".
        os.startfile("spotify:")
        limit = time.time() + 20
        while time.time() < limit and spotify_window() is None:
            time.sleep(0.5)
        time.sleep(4)
    _spotify_search(query, SPOTIFY_WAIT)
    ok = _click_top_result(was_open)
    time.sleep(1.5)
    info = spotify_media("info") if ok else None
    # "almohada de jose jose" a veces pone al artista: si no suena la cancion pedida, busca solo canciones
    m = re.fullmatch(r"(.+)\s+(?:de|del|by|from)\s+(.+)", query.strip(), flags=re.I)
    if info and info[0] and m and not (_words(m.group(1)) & _words(info[0])):
        _spotify_search(f'track:"{m.group(1)}" artist:"{m.group(2)}"', SPOTIFY_WAIT)
        if _click_top_result(True):
            time.sleep(1.5)
            info = spotify_media("info") or info
    if info and info[0]:
        speak(f"Playing {info[0]} by {info[1]}.")
    else:
        speak("I found it on Spotify, but I could not start it. Press play on the top result.")


def music(action):
    result = spotify_media(action)
    if result is False and action == "play":
        os.startfile("spotify:")
        speak("Opening Spotify.")
        time.sleep(5)
        result = spotify_media("play")
    if result is False:
        speak("Spotify is not open.")
    elif action == "info":
        title, artist = result if result else ("", "")
        speak(f"This is {title} by {artist}." if title else "I cannot tell what is playing.")
    elif action in ("next", "previous"):
        speak("Next song." if action == "next" else "Previous song.")
    return True


# ======================= OIDO =======================
audio_q = queue.Queue(maxsize=int(30 / BLOCK))  # hasta 30 s de audio pendiente
mic = {"rate": 16000}


def flush_audio():
    """Descarta el audio pendiente, por ejemplo la propia voz de Jarvis."""
    while True:
        try:
            audio_q.get_nowait()
        except queue.Empty:
            return


def mic_loop():
    """Mantiene el microfono abierto siempre: nada se pierde mientras Jarvis piensa.

    Tambien detecta dos aplausos cuando Jarvis esta en espera.
    """
    while True:
        try:
            rate = int(sd.query_devices(MIC_INDEX, "input")["default_samplerate"])
            mic["rate"] = rate
            size = int(rate * BLOCK)
            burst = blocks = 0
            prev_peak = 0.0
            last_clap = None
            with sd.InputStream(samplerate=rate, channels=1, dtype="int16",
                                device=MIC_INDEX, blocksize=size) as stream:
                while True:
                    data, _ = stream.read(size)
                    data = data.copy()
                    if audio_q.full():  # si se acumula demasiado, se tira lo mas viejo
                        try:
                            audio_q.get_nowait()
                        except queue.Empty:
                            pass
                    audio_q.put_nowait(data)
                    blocks += 1
                    now = blocks * BLOCK
                    peak = float(np.max(np.abs(data[:, 0]))) / 32768.0
                    if CLAP_ENABLED and S["state"] == "sleep":
                        if peak >= CLAP_LEVEL and (burst > 0 or prev_peak < peak * 0.5):
                            burst += 1
                        else:
                            if 0 < burst <= 5:  # golpe corto: parece un aplauso
                                if last_clap is not None and 0.12 <= now - last_clap <= 0.9:
                                    print("Aplausos detectados")
                                    last_clap = None
                                    events.put("clap")
                                else:
                                    last_clap = now
                            burst = 0
                    prev_peak = peak
        except Exception as e:
            print("Microfono:", e)
            time.sleep(2)


def record(seconds, idle=False):
    """Toma del microfono desde que empiezas a hablar hasta que te callas.

    En espera (idle) no tiene limite. Si no, devuelve None cuando pasan
    `seconds` sin que hables.
    """
    preroll = collections.deque(maxlen=int(0.5 / BLOCK))
    recent = collections.deque(maxlen=10)  # basta con que la mitad suene a voz
    speech = []
    noise = 0.003
    silent = 0
    end_level = 0.0
    start = time.time()
    while True:
        if idle and not (events.empty() and telefono.inbox.empty() and telefono.signals.empty()):
            return None
        try:
            data = audio_q.get(timeout=0.2)
        except queue.Empty:
            if not idle and time.time() - start > seconds:
                return None
            continue
        x = data[:, 0].astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(x * x)))
        threshold = max(noise * 2.5, MIN_VOICE)
        if not speech:
            preroll.append(data.tobytes())
            recent.append(rms > threshold)
            if sum(recent) >= 5:
                speech = list(preroll)
                end_level = threshold * 0.6  # no te corta si bajas un poco la voz
            elif sum(recent) <= 1:
                noise = min(noise * 0.95 + rms * 0.05, 0.02)
            if not speech and not idle and time.time() - start > seconds:
                return None
        else:
            speech.append(data.tobytes())
            silent = silent + 1 if rms <= end_level else 0
            if silent * BLOCK >= SILENCE_END or len(speech) * BLOCK >= MAX_SPEECH:
                return sr.AudioData(b"".join(speech), mic["rate"], 2)


def _google(audio, lang):
    """[(texto, confianza), ...] con todas las opciones de Google, [] si no entendio, None sin conexion."""
    try:
        res = recognizer.recognize_google(audio, language=lang, show_all=True)
    except sr.UnknownValueError:  # no entendio nada (ruido o silencio): no es un error
        return []
    except sr.RequestError as e:
        print(f"Google ({lang}) no disponible:", e)
        return None
    except Exception as e:
        print(f"Google ({lang}) no respondio: {type(e).__name__} {e}")
        return None
    if not res or not res.get("alternative"):
        return []
    alts = res["alternative"]
    first = float(alts[0].get("confidence", 0.5))
    return [(a.get("transcript", "").lower().strip(), first if i == 0 else first * 0.6)
            for i, a in enumerate(alts) if a.get("transcript")]


def transcribe(audio, want_wake=False):
    """Pide a Google ingles y español a la vez y elige la mejor frase. None = sin internet.

    Con want_wake, prefiere cualquier opcion que contenga 'Jarvis', aunque no sea la primera.
    """
    jobs = [pool.submit(_google, audio, lang) for lang in LANGUAGES]
    done, _ = wait(jobs, timeout=GOOGLE_TIMEOUT)  # no espera al idioma que tarde de mas
    results = [job.result() for job in done]
    if not any(r is not None for r in results):
        return None
    options = [opt for r in results if r for opt in r]
    best, score = "", -1.0
    for text, conf in options:
        rest = strip_wake(text)
        bonus = 0.35 if comandos.is_command(rest) else 0.0  # parece una orden
        if want_wake and rest != text:
            bonus += 1.0  # lo llamaron por su nombre
        if conf + bonus > score:
            best, score = text, conf + bonus
    return best


def listen(seconds=6, idle=False):
    """Texto oido, '' si no se entendio, None si no hablaste. Sin internet devuelve False."""
    if S.get("phone") and not idle:  # la conversacion es con el celular
        try:
            text = telefono.inbox.get(timeout=max(seconds, 20))
        except queue.Empty:
            return None
        print("Phone:", text)
        return text
    audio = record(seconds, idle)
    if audio is None:
        return None
    text = transcribe(audio, want_wake=idle)
    if text is None:  # Google fallo: un segundo intento antes de rendirse
        text = transcribe(audio, want_wake=idle)
    if text is None:
        return False
    if text:
        print("Heard:", text)
    return text


def strip_wake(text):
    """Quita 'Jarvis' o 'Talos' (o algo parecido) del principio."""
    text = text.lower().strip(" ,.")
    words = text.split()
    for i, word in enumerate(words[:5]):
        w = word.strip(" ,.?!")
        if w in WAKE_WORDS or difflib.SequenceMatcher(None, w, "jarvis").ratio() >= 0.7:
            return " ".join(words[i + 1:]).strip(" ,.")
    return text


def has_wake(text):
    return strip_wake(text) != text.lower().strip(" ,.")


# ======================= VOZ =======================
def heard_stop(audio, found):
    text = " ".join(t for r in pool.map(lambda lang: _google(audio, lang), LANGUAGES) if r for t, _ in r)
    if re.search(STOP_WORDS, comandos._strip(text.lower())):
        found.set()


def listen_for_stop(duration):
    """Escucha mientras Jarvis habla. True si le dijeron stop o hicieron clic."""
    found = threading.Event()
    end = time.time() + duration + 0.1
    recent = collections.deque(maxlen=int(1.0 / BLOCK))  # su propia voz, de fondo
    window = collections.deque(maxlen=int(1.1 / BLOCK))
    wait_blocks = 0
    checker = None
    while time.time() < end:
        if found.is_set() or S.get("stop"):
            return True
        try:
            data = audio_q.get(timeout=0.1)
        except queue.Empty:
            continue
        x = data[:, 0].astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(x * x)))
        window.append(data.tobytes())
        if wait_blocks > 0:
            wait_blocks -= 1
            if wait_blocks == 0 and (checker is None or not checker.is_alive()):
                audio = sr.AudioData(b"".join(window), mic["rate"], 2)
                checker = threading.Thread(target=heard_stop, args=(audio, found), daemon=True)
                checker.start()
        elif len(recent) >= 5 and rms > max(STOP_LEVEL, float(np.median(recent)) * 1.5):
            wait_blocks = int(0.8 / BLOCK)  # algo suena mas fuerte que Jarvis
        recent.append(rms)
    return found.is_set()


def speak(text):
    text = re.sub(r"[*#_`>]+", "", text).strip()
    if not text:
        return
    if agent["on"] and re.match(FAIL_TEXT, text):
        agent["fails"].append(text)  # la IA lo vera y probara otra cosa
        print("  (no pudo:", text + ")")
        return
    print("Jarvis:", text)
    set_state("speaking", text)
    with wave.open(TTS_FILE, "wb") as f:
        voice.synthesize_wav(text, f)
    if S.get("phone"):  # la orden vino del celular: la respuesta va para alla, con la voz de Jarvis
        try:
            telefono.send("#AUDIO " + base64.b64encode(voice_file()).decode("ascii"))
            telefono.send("#TEXT " + text)
        except Exception as e:
            print("Voz para el celular:", e)
            telefono.send(text)  # el telefono la lee con su propia voz
        if not PHONE_ALOUD:
            return
    with wave.open(TTS_FILE, "rb") as f:
        duration = f.getnframes() / f.getframerate()
    S.pop("stop", None)
    winsound.PlaySound(TTS_FILE, winsound.SND_FILENAME | winsound.SND_ASYNC)
    if listen_for_stop(duration):
        winsound.PlaySound(None, winsound.SND_PURGE)
        print("Jarvis detenido")
    flush_audio()  # no escucharse a si mismo


def voice_file():
    """Lo ultimo que dijo Jarvis, comprimido en MP3 para que viaje rapido por Bluetooth."""
    try:
        import av
    except ImportError:
        with open(TTS_FILE, "rb") as f:  # sin compresor: se manda el WAV tal cual (tarda mas)
            return f.read()
    out_file = io.BytesIO()
    with av.open(TTS_FILE) as src, av.open(out_file, "w", format="mp3") as out:
        rate = src.streams.audio[0].rate
        stream = out.add_stream("libmp3lame", rate=rate)
        stream.bit_rate = 48000
        resampler = av.AudioResampler(format=stream.format, layout="mono", rate=rate,
                                      frame_size=stream.frame_size or 1152)
        for frame in src.decode(audio=0):
            for part in resampler.resample(frame):
                for packet in stream.encode(part):
                    out.mux(packet)
        for part in resampler.resample(None):
            for packet in stream.encode(part):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return out_file.getvalue()


def confirm(prompt):
    speak(prompt + " Say yes to confirm.")
    set_state("listening", "Say yes to confirm")
    winsound.Beep(900, 120)
    answer = comandos._strip(comandos.clean(listen() or ""))  # "Si", "Sí" y "YES" valen igual
    return bool(re.search(r"\b(yes|yeah|yep|si|dale|claro|envialo|mandalo|send it|ok|okay|hazlo)\b", answer))


# ======================= IA =======================
def chat(messages):
    kwargs = dict(model=MODEL, messages=messages, keep_alive=KEEP_ALIVE, options={"num_predict": 300})
    try:
        return ollama.chat(think=False, **kwargs)["message"]["content"]
    except Exception as e:
        if "think" not in str(e).lower():
            raise
        return ollama.chat(**kwargs)["message"]["content"]


def warm_up():
    """Carga la IA al abrir Jarvis, para que la primera respuesta no tarde."""
    try:
        ollama.generate(model=MODEL, prompt="", keep_alive=KEEP_ALIVE)
        print("IA lista:", MODEL)
    except Exception as e:
        print("No pude cargar la IA:", e)


last_shot = {"image": None, "time": 0.0}


def grab_screen():
    """Captura la pantalla y la guarda para las preguntas que sigan."""
    img = pyautogui.screenshot()
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    last_shot.update(image=buf.getvalue(), time=time.time())


def run_action(command):
    """Ejecuta una orden y devuelve (salio bien, detalle para la IA)."""
    if command == "exit":
        return False, "That command does not exist."
    agent.update(on=True, fails=[], info=[])
    try:
        known = handle(command)
    except Exception as e:
        print("Orden:", e)
        agent["fails"].append(f"Error: {e}")
        known = True
    finally:
        agent["on"] = False
    if not known:
        return False, "That command does not exist; use only the commands on the list."
    if agent["fails"]:
        detail = " ".join(agent["fails"])
        if command.startswith("open ") and not command.startswith("open file "):
            detail += " " + app_hint(command[5:])
        return False, detail
    return True, " ".join(agent["info"])


def results_text(results):
    lines = "\n".join(f"- {c}: {'OK' if ok else 'FAILED'}{'. ' + d if d else ''}" for c, ok, d in results)
    return ("RESULTS (from the PC, not from the user):\n" + lines + "\nIf something FAILED, work out what the "
            "user really meant and try a different DO: command (do not repeat the ones that are OK), or tell "
            "the user briefly that it could not be done. If everything is done, reply with one short sentence.")


def ask_ai(question, look=False, tried=None):
    """La IA responde o actua. Ve el resultado de cada orden y puede corregirse (hasta 3 intentos).

    tried = (orden, detalle): una orden directa que ya fallo, para que la IA la resuelva.
    """
    global history
    if look:
        set_state("thinking", "Looking at your screen...")
        grab_screen()
    recent = last_shot["image"] and time.time() - last_shot["time"] < SCREEN_MEMORY
    now = datetime.datetime.now().strftime("%A %d %B %Y, %I:%M %p")
    system = f"{SYSTEM_PROMPT} Now it is {now}."
    if phone_state["call"] == "ringing":
        system += (f" RIGHT NOW the user's phone is ringing: {phone_state['who']} is calling. If what they say "
                   "means they want to take it, do 'answer call'; if they do not want it, do 'end call'.")
    elif phone_state["call"] == "active":
        system += " RIGHT NOW the user is on a phone call; 'end call' hangs up."
    fresh = [(who, text) for who, text, when in wa_messages if time.time() - when < 1800]
    if fresh:
        system += (" Recent WhatsApp messages on the user's phone (newest last): "
                   + "; ".join(f"{who} wrote: {text}" for who, text in fresh[-5:])
                   + ". If the user wants to answer one, use 'whatsapp reply to <name>: <message>'.")
    message = {"role": "user", "content": question}
    if recent:
        system += " " + VISION_PROMPT
        message["images"] = [last_shot["image"]]
    messages = [{"role": "system", "content": system}] + history + [message]
    if tried:
        messages += [{"role": "assistant", "content": "DO: " + tried[0]},
                     {"role": "user", "content": results_text([(tried[0], False, tried[1])])}]
    said, final = [], ""
    for _ in range(3):
        set_state("thinking", question)
        try:
            answer = chat(messages)
        except Exception as e:
            print("Ollama:", e)
            speak("I cannot reach my AI. Make sure Ollama is running.")
            return
        said.append(answer)
        actions = [a.strip().strip(".'\"` ") for a in re.findall(r"^\W*DO:\s*(.+)$", answer, flags=re.M | re.I)]
        if not actions:
            final = answer.strip() or "Sorry, I did not get that."
            speak(final)
            break
        results = []
        for i, action in enumerate(actions):
            command = comandos.to_command(action)
            print("IA hace:", command)
            ok, detail = run_action(command)
            results.append((command, ok, detail))
            if ok and command.startswith(("open ", "switch to ")) and i + 1 < len(actions):
                time.sleep(2)  # deja que la app se abra antes de la siguiente orden
        if all(ok and not detail for _, ok, detail in results):
            break  # todo salio bien y cada orden ya lo dijo
        messages += [{"role": "assistant", "content": answer},
                     {"role": "user", "content": results_text(results)}]
    else:
        speak("Sorry, I could not do that.")
    history = (history + [{"role": "user", "content": question},
                          {"role": "assistant", "content": "\n".join(said)}])[-12:]


# ======================= TECLADO, RATON Y VENTANAS =======================
def press_keys(spec):
    spec = spec.replace(" plus ", " ").replace("page up", "pageup").replace("page down", "pagedown")
    keys = [KEYMAP.get(k, k) for k in spec.split()]
    if not keys or any(k not in pyautogui.KEYBOARD_KEYS for k in keys):
        return False
    pyautogui.hotkey(*keys)
    return True


def click_by_name(name, mode):
    import win32gui
    from pywinauto import Desktop
    window = Desktop(backend="uia").window(handle=win32gui.GetForegroundWindow())
    best = None
    for el in window.descendants():
        try:
            text = (el.window_text() or "").lower()
            if text and name in text and el.is_visible() and (best is None or len(text) < len(best[0])):
                best = (text, el)
        except Exception:
            pass
    if not best:
        return None
    {"double": best[1].double_click_input, "right": best[1].right_click_input}.get(mode, best[1].click_input)()
    return best[0]


def focus_window(name):
    import win32con
    import win32gui
    found = []
    win32gui.EnumWindows(lambda h, _: found.append(h) if win32gui.IsWindowVisible(h)
                         and name in win32gui.GetWindowText(h).lower() else None, None)
    if not found:
        return None
    if win32gui.IsIconic(found[0]):
        win32gui.ShowWindow(found[0], win32con.SW_RESTORE)
    try:
        pyautogui.press("alt")
        win32gui.SetForegroundWindow(found[0])
    except Exception as e:
        print("Ventana:", e)
    return win32gui.GetWindowText(found[0])


def take_screenshot():
    os.makedirs(SHOT_DIR, exist_ok=True)
    limit = time.time() - 3600  # borra capturas de mas de una hora
    for name in os.listdir(SHOT_DIR):
        path = os.path.join(SHOT_DIR, name)
        if name.startswith("shot_") and os.path.getmtime(path) < limit:
            os.remove(path)
    pyautogui.screenshot().save(os.path.join(SHOT_DIR, datetime.datetime.now().strftime("shot_%Y%m%d_%H%M%S.png")))


def timer_done(what):
    print("*** Temporizador:", what)
    for _ in range(3):
        winsound.Beep(1000, 600)


# ======================= ORDENES =======================
def handle(c):
    """Ejecuta una orden en ingles. False = no es una orden y va a la IA."""
    if c == "active game night":
        n = gamer_mode()
        game = find_desktop_app(GAME_NIGHT_APP)
        if game:
            speak(f"Game night active. I closed {n} background apps. Opening {GAME_NIGHT_APP}.")
            os.startfile(game)
        else:
            speak(f"Game night active. I closed {n} background apps, but I could not find {GAME_NIGHT_APP}.")
        return True
    if c == "active gamer mode":
        n = gamer_mode()
        speak(f"Gamer mode active. I closed {n} background apps.")
        return True
    if c == "exit":
        speak("Goodbye.")
        os._exit(0)

    # --- telefono (por Bluetooth, con la app Talos) ---
    phone = {"answer call": ("#ANSWER", "Answering."), "end call": ("#HANGUP", "Call ended."),
             "phone pause music": ("#PAUSE", "Paused on your phone."),
             "phone resume music": ("#PLAY", "Playing on your phone."),
             "phone next song": ("#NEXT", "Next song on your phone."),
             "phone previous song": ("#PREV", "Previous song on your phone."),
             "phone volume up": ("#VOLUP", "Phone volume up."),
             "phone volume down": ("#VOLDOWN", "Phone volume down.")}
    if c == "read messages":
        fresh = [(who, text) for who, text, when in wa_messages if time.time() - when < 3600]
        if not fresh:
            speak("There are no new WhatsApp messages.")
        for who, text in fresh[-3:]:
            speak(f"{who} says: {text}")
        return True
    m = re.fullmatch(r"whatsapp audio(?: to ([^:]*))?:\s*(.+)", c)
    if m:
        whatsapp_audio((m.group(1) or "").strip(), m.group(2).strip())
        return True
    m = re.fullmatch(r"whatsapp reply(?: to ([^:]*))?:\s*(.+)", c)
    if m:
        whatsapp_send((m.group(1) or "").strip(), m.group(2).strip())
        return True
    m = re.fullmatch(r"phone play (.+)", c)
    if m:
        speak(f"Looking for {m.group(1)} on your phone." if telefono.send("#PLAYSEARCH " + m.group(1))
              else "Your phone is not connected.")
        return True
    m = re.fullmatch(r"phone volume (\d{1,3})", c)
    if m:
        level = min(100, int(m.group(1)))
        speak(f"Phone volume {level} percent." if telefono.send(f"#VOL {level}") else "Your phone is not connected.")
        return True
    if c in phone:
        order, done = phone[c]
        speak(done if telefono.send(order) else "Your phone is not connected.")
        return True

    # --- Spotify ---
    actions = {"pause music": "pause", "resume music": "play", "next song": "next",
               "previous song": "previous", "what is playing": "info"}
    if c in actions:
        return music(actions[c])
    m = re.fullmatch(r"spotify volume (up|down|\d+)", c)
    if m or c in ("mute spotify", "unmute spotify"):
        if m and m.group(1).isdigit():
            level = spotify_volume(level=int(m.group(1)) / 100)
        elif m:
            level = spotify_volume(change=SPOTIFY_STEP if m.group(1) == "up" else -SPOTIFY_STEP)
        else:
            level = spotify_volume(mute=(c == "mute spotify"))
        if level is None:
            speak("Spotify is not playing right now.")
        elif c.startswith(("mute", "unmute")):
            speak("Spotify muted." if c == "mute spotify" else "Spotify unmuted.")
        else:
            speak(f"Spotify volume {level} percent.")
        return True
    if c == "spotify ask":  # dijiste "busca en Spotify" sin decir que
        speak("What should I play on Spotify?")
        set_state("listening", "Listening...")
        text = listen(10)
        if text:
            spotify_play(re.sub(r"^(play|pon|ponme|busca|reproduce) ", "", strip_wake(text).strip()))
        elif text is not False:
            speak("I did not catch the song.")
        return True
    m = re.fullmatch(r"play (.+) on youtube", c)
    if m:
        webbrowser.open("https://www.youtube.com/results?search_query=" + quote(m.group(1)))
        speak(f"Searching {m.group(1)} on YouTube.")
        return True
    m = re.fullmatch(r"play (.+?)( on spotify)?", c)
    if m:
        spotify_play(m.group(1))
        return True

    # --- pantalla ---
    if "screenshot" in c:
        take_screenshot()
        speak("Screenshot saved.")
        return True

    # --- teclado y raton ---
    if c.startswith("type "):
        text = c[5:]
        if text.isascii():
            pyautogui.write(text, interval=0.02)
        else:  # acentos y eñes se pegan desde el portapapeles
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        speak("Typed.")
        return True
    if c.startswith("press "):
        speak("Done." if press_keys(c[6:]) else "I do not know that key.")
        return True
    if c == "close window":
        if confirm("Close the current window?"):
            pyautogui.hotkey("alt", "f4")
            speak("Closed.")
        else:
            speak("Cancelled.")
        return True
    shortcut = next((k for k in SHORTCUTS if c == k or (" " in k and k in c)), None)
    if shortcut:
        m = re.search(r" (?:in|on|en) ([a-z0-9 ]+)$", c)
        if m:
            focus_window(m.group(1).strip())
            time.sleep(0.5)
        pyautogui.hotkey(*(("ctrl", "n") if shortcut == "new tab" and "notepad" in c else SHORTCUTS[shortcut]))
        speak("Done.")
        return True
    for prefix, mode in (("double click ", "double"), ("right click ", "right"), ("click ", "click")):
        if c.startswith(prefix):
            name = c[len(prefix):].strip()
            try:
                hit = click_by_name(name, mode)
            except Exception as e:
                print("Clic:", e)
                hit = None
            speak(f"Clicked {hit}." if hit else f"I could not find {name} on this window.")
            return True
    if c.startswith("scroll"):
        w, h = pyautogui.size()
        pyautogui.moveTo(w // 2, h // 2)
        pyautogui.scroll(-600 if "down" in c else 600)
        return True
    if c.startswith("switch to "):
        got = focus_window(c[10:].strip())
        speak(f"Switched to {got}." if got else f"I could not find a window named {c[10:]}.")
        return True

    # --- apps y web ---
    if c.startswith("open file "):
        path = pick_file(c[10:])
        if path:
            os.startfile(path)
            speak(f"Opening {os.path.basename(path)}.")
        else:
            speak(f"I could not find the file {c[10:]}.")
        return True
    if c.startswith("find "):
        m = re.fullmatch(r"find (.*?)(?: (?:in|en|on) (?:the |my |mi |la )?([\w ]+?)(?: folder)?)?", c)
        what, folder = (m.group(1), m.group(2)) if m else (c[5:], None)
        if folder and not folder_path(folder):
            what, folder = c[5:], None
        files = find_files(what, folder)
        if not files:
            speak("I could not find any file like that.")
        else:
            listing = "; ".join(f"{i}. {os.path.basename(p)} ({time.strftime('%d %b %Y', time.localtime(t))})"
                                for i, (t, p) in enumerate(files, 1))
            agent["info"].append("Newest matches: " + listing + ". Tell the user what you found, briefly, "
                                 "or open one with 'open file <number>' if they asked for that.")
            if not agent["on"]:
                speak(f"I found {len(files)} files. The newest is {os.path.basename(files[0][1])}.")
        return True
    if c.startswith("open "):
        name = c[5:].strip()
        if re.fullmatch(r"(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?", name):
            webbrowser.open(name if name.startswith("http") else "https://" + name)
            speak(f"Opening {name}.")
            return True
        got = open_app(name)
        speak(f"Opening {got}." if got else f"I could not find {name}.")
        return True
    if c.startswith("close ") and c not in ("close window", "close tab"):
        name = c[6:].strip()
        got = close_app(name)
        speak(f"Closing {got}." if got else f"I could not find {name} open.")
        return True
    if c.startswith("search "):
        webbrowser.open("https://www.google.com/search?q=" + quote(c[7:]))
        speak(f"Searching {c[7:]}.")
        return True
    if "weather" in c:
        webbrowser.open("https://www.google.com/search?q=weather")
        speak("Showing the weather.")
        return True

    # --- hora, volumen, notas y temporizador ---
    if "what time" in c or c in ("time", "the time"):
        speak(datetime.datetime.now().strftime("It is %I:%M %p."))
        return True
    if "what date" in c or "today's date" in c:
        speak(datetime.datetime.now().strftime("Today is %A, %d %B %Y."))
        return True
    if "volume up" in c or "volume down" in c:
        for _ in range(5):
            pyautogui.press("volumeup" if "up" in c else "volumedown")
        speak("Volume up." if "up" in c else "Volume down.")
        return True
    if c in ("mute", "mute the volume"):
        pyautogui.press("volumemute")
        return True
    if c.startswith("note "):
        with open(os.path.join(HERE, "notes.txt"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M} - {c[5:]}\n")
        speak("Note saved.")
        return True
    m = re.fullmatch(r"timer (\d+) (second|minute|hour)", c)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        threading.Timer(n * {"second": 1, "minute": 60, "hour": 3600}[unit], timer_done, args=(c,)).start()
        speak(f"Timer set for {n} {unit}{'s' if n != 1 else ''}.")
        return True
    return False


def run(text):
    """Orden o pregunta. Devuelve False si dijiste que ya terminaste."""
    said = strip_wake(text)
    if not said:
        return True
    plain = comandos._strip(comandos.clean(said))
    words = plain.split()  # "listo listo" = "listo"; "eh thank you" = "thank you"
    while len(words) > 1 and words[0] in ("eh", "uh", "ah", "um", "ok", "okay", "bueno", "ya", "si"):
        words = words[1:]
    if len(words) % 2 == 0 and words[:len(words) // 2] == words[len(words) // 2:]:
        words = words[:len(words) // 2]
    if re.fullmatch(END_WORDS, " ".join(words)):
        speak("Anytime.")
        return False
    command = comandos.to_command(said)
    set_state("thinking", said)
    only_save = command == "screenshot" and not re.search(LOOK_VERBS, plain)
    if re.search(SCREEN_WORDS, plain) and not only_save:
        ask_ai(said, look=True)  # mira la pantalla y responde
    elif needs_ai(command):
        ask_ai(said)  # la IA decide que hacer y lo hace con lineas DO:
    else:
        agent.update(on=True, fails=[], info=[])
        try:
            known = handle(command)
        finally:
            agent["on"] = False
        if not known:
            ask_ai(said)
        elif agent["fails"]:  # la orden directa fallo: que la IA piense que quisiste decir
            detail = " ".join(agent["fails"])
            if command.startswith("open "):
                detail += " " + app_hint(command[5:])
            ask_ai(said, tried=(command, detail))
    return True


def needs_ai(command):
    """Las ordenes simples van directo (mas rapido); las compuestas o vagas las piensa la IA."""
    if command.startswith(("find ", "open file ")):
        return True
    m = re.match(r"(open|close|search|play|click|double click|right click|switch to|note) (.+)", command)
    if not m:
        return False
    arg = comandos._strip(m.group(2))
    if re.search(r"\b(cel|celular|telefono|phone|movil|llamada|call|la que sigue|la siguiente|la anterior)\b", arg):
        return True  # habla del telefono o de "la que sigue": que lo razone la IA
    if m.group(1) == "search" and re.search(r"\b(archivos?|carpetas?|descargas|documentos|escritorio|files?|folders?"
                                            r"|downloads|documents|desktop|mi pc|my pc|mi computadora)\b", arg):
        return True  # buscar en el PC, no en Google
    return bool(re.search(r"\b(y|and|then|luego|despues|tambien|also)\b", arg)
                or re.match(r"(eso|esto|esa|ese|esta|este|it|that|this|algo|something|lo que|what)\b", arg))


def conversation(first=None):
    """Atiende una orden y sigue escuchando sin que vuelvas a activarlo."""
    last_shot["image"] = None  # cada conversacion empieza sin captura
    text = first
    if text is None:
        speak(GREETING)
        set_state("listening", "Listening...")
        winsound.Beep(900, 120)
        text = listen()
        if text is False:
            speak("I need internet to understand you.")
            return
        if not text:
            speak("I did not hear anything." if text == "" else "I am here if you need me.")
            return
    while text:
        if not run(text):
            return
        set_state("listening", "Listening...")
        text = listen(FOLLOW_UP_SECONDS)
        if text is False:
            return


def phone_ask(order, answer, seconds=4):
    """Le pide algo a la app del telefono y espera su respuesta ("#ANSWER ...")."""
    if not telefono.send("#" + order):
        return None
    other, found, limit = [], None, time.time() + seconds
    while time.time() < limit and found is None:
        try:
            signal = telefono.signals.get(timeout=0.2)
        except queue.Empty:
            continue
        if signal.startswith(answer + " "):
            found = signal[len(answer) + 1:]
        else:
            other.append(signal)
    for signal in other:  # lo demas que llego mientras tanto no se pierde
        telefono.signals.put(signal)
    return found


def full_number(raw):
    """Numero listo para WhatsApp: solo digitos y con codigo de pais."""
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+"):
        return digits
    if digits.startswith("00"):
        return digits[2:]
    if digits.startswith("0"):
        return COUNTRY_CODE + digits[1:]   # 0414... -> 58414...
    if len(digits) <= 10:
        return COUNTRY_CODE + digits
    return digits


def contact_number(name):
    """(nombre, numero) de un contacto del telefono, o None. Recuerda los ya vistos."""
    key = comandos._strip(name.lower()).strip()
    try:
        with open(CONTACTS_FILE, encoding="utf-8") as f:
            known = json.load(f)
    except Exception:
        known = {}
    if key not in known:
        reply = phone_ask("CONTACT " + name, "NUMBER")
        if reply is None:
            print("Contactos: el celular no respondio (¿app sin actualizar o sin conexion?)")
            return None
        parts = reply.split("|")
        if len(parts) > 3 and parts[3].strip() == "NOPERM":
            print("Contactos: la app Talos no tiene permiso de contactos en el telefono")
            return None
        if len(parts) < 3 or not parts[2].strip():
            print(f"Contactos: el telefono no tiene ningun contacto llamado {name}")
            return None
        known[key] = [parts[1].strip(), full_number(parts[2])]
        try:
            with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
                json.dump(known, f, ensure_ascii=False, indent=1)
        except Exception as e:
            print("Contactos:", e)
    return tuple(known[key])


def whatsapp_window():
    """Abre WhatsApp de escritorio, lo trae al frente y devuelve su ventana (pywinauto) o None."""
    import win32gui
    from pywinauto import Desktop
    if not focus_window("whatsapp"):
        os.startfile("whatsapp:")
        time.sleep(WHATSAPP_WAIT)
        if not focus_window("whatsapp"):
            return None
    time.sleep(0.6)
    return Desktop(backend="uia").window(handle=win32gui.GetForegroundWindow())


def name_score(key, text):
    """Que tan bien coincide el titulo de un chat con el nombre dicho. Menos es mejor; None = no es."""
    if text == key:
        return 0
    if not text or len(text) > 45:
        return None  # es un mensaje, no el titulo de un chat
    if text.startswith(key + " "):
        return 1 + len(text)
    if key in text.split():           # "trueno" -> "Pepe Trueno"
        return 100 + len(text)
    if len(key) >= 4 and key in text:
        return 200 + len(text)
    # parecido palabra por palabra, en cualquier orden: "futbol amigos" -> "amigos del futbol"
    said = [w for w in re.findall(r"[a-z0-9]+", key) if len(w) >= 3]
    have = re.findall(r"[a-z0-9]+", text)
    if not said or not have:
        return None
    close = sum(max(difflib.SequenceMatcher(None, w, h).ratio() for h in have) for w in said) / len(said)
    return 300 + (1 - close) * 100 if close >= 0.78 else None


def chat_title(text):
    """Titulo de un chat a partir de su fila: "5 mensajes no leidos Curso LLA-113 10:18" -> "Curso LLA-113"."""
    title = re.sub(r"^\d+ mensajes? no le[ií]dos? ", "", text.strip(), flags=re.I)
    title = re.sub(r"^\d+ unread messages? ", "", title, flags=re.I)
    when = (r"\s+(\d{1,2}:\d{2}(\s*[ap]\.?\s*m\.?)?|ayer|hoy|yesterday|today|lunes|martes|mi[eé]rcoles|jueves|viernes"
            r"|s[aá]bado|domingo|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}/\d{1,2}/\d{2,4})$")
    return re.sub(when, "", title, flags=re.I).strip()


def whatsapp_open_chat(name):
    """Busca el chat (persona o grupo) en WhatsApp de escritorio y lo abre. Devuelve su titulo o None.

    Usa el buscador del propio WhatsApp, que ya tolera nombres aproximados, y elige el resultado
    que mas se parece a lo que dijiste.
    """
    window = whatsapp_window()
    if window is None:
        return None
    area = window.rectangle()
    limit = area.left + (area.right - area.left) * 0.45  # la lista de chats esta a la izquierda
    box = next((el for el in window.descendants(control_type="Edit")
                if el.is_visible() and el.rectangle().left < limit), None)
    if box is None:
        print("WhatsApp: no encontre el cuadro de busqueda")
        return None
    box.click_input()
    pyautogui.hotkey("ctrl", "a")
    pyperclip.copy(name)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(2.5)

    key = comandos._strip(name.lower()).strip()
    rows, seen = [], set()
    for grid in window.descendants(control_type="DataGrid"):
        try:
            g = grid.rectangle()
            # WhatsApp guarda por dentro copias viejas de la lista: solo vale la que esta en pantalla
            if g.left > limit or not grid.is_visible() or not (area.top < g.top < area.bottom):
                continue
            for item in grid.descendants(control_type="DataItem"):
                r = item.rectangle()
                text = (item.window_text() or "").strip()
                if comandos._strip(text.lower()) in ("mensajes", "messages"):
                    break  # de aqui para abajo son mensajes que contienen la palabra, no chats
                # la fila del titulo es la bajita (unos 25 px); las otras llevan tambien el ultimo mensaje
                if not text or not 15 <= r.height() <= 40 or (r.left, r.top) in seen:
                    continue
                if not (area.top < r.top < area.bottom):
                    continue
                seen.add((r.left, r.top))
                title = chat_title(text)
                if title:
                    rows.append((r.top, item, title))
        except Exception as e:
            print("WhatsApp (leer resultados):", e)
    if not rows:
        print("WhatsApp: la busqueda de", name, "no dio resultados")
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        return None
    rows.sort(key=lambda row: row[0])
    scored = [(name_score(key, comandos._strip(title.lower())), top, item, title) for top, item, title in rows]
    good = sorted((x for x in scored if x[0] is not None), key=lambda x: (x[0], x[1]))
    print("WhatsApp: resultados:", ", ".join(t for _, _, t in rows[:5]))
    if not good:  # ninguno se parece a lo que pediste: mejor no escribirle a nadie
        print("WhatsApp: ninguno coincide con", name)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        return None
    _, _, item, title = good[0]
    print("WhatsApp: elegido:", title)
    item.click_input()
    time.sleep(1.5)
    # comprueba que el chat que quedo abierto es el elegido, antes de escribir nada
    opened = ""
    for el in window.descendants(control_type="Text"):
        try:
            r = el.rectangle()
            if r.left > limit and area.top + 30 < r.top < area.top + 100 and (el.window_text() or "").strip():
                opened = el.window_text().strip()
                break
        except Exception:
            pass
    same = comandos._strip(opened.lower()) == comandos._strip(title.lower())
    print("WhatsApp: chat abierto:", opened or "(no pude leerlo)")
    if not same:
        print("WhatsApp: el chat abierto no es el elegido; no escribo nada")
        whatsapp_clear_search()
        return None
    boxes = [el for el in window.descendants(control_type="Edit")
             if el.is_visible() and el.rectangle().left > limit and area.top < el.rectangle().top < area.bottom]
    if not boxes:
        print("WhatsApp: abri el chat pero no encontre donde escribir")
        return None
    max(boxes, key=lambda el: el.rectangle().top).click_input()  # el cuadro "Escribe un mensaje"
    time.sleep(0.3)
    return title


def make_audio(text):
    """Graba `text` con la voz de Jarvis en un archivo de audio y devuelve su ruta."""
    os.makedirs(AUDIO_DIR, exist_ok=True)
    limit = time.time() - 7 * 86400  # borra los audios de hace mas de una semana
    for old in os.listdir(AUDIO_DIR):
        path = os.path.join(AUDIO_DIR, old)
        if old.startswith("jarvis_") and os.path.getmtime(path) < limit:
            os.remove(path)
    with wave.open(TTS_FILE, "wb") as f:
        voice.synthesize_wav(text, f)
    data = voice_file()
    kind = "mp3" if data[:3] == b"ID3" or data[:1] == b"\xff" else "wav"
    path = os.path.join(AUDIO_DIR, time.strftime("jarvis_%Y%m%d_%H%M%S.") + kind)
    with open(path, "wb") as f:
        f.write(data)
    return path


def make_voice_note(text):
    """Graba `text` con la voz de TALOS como nota de voz de WhatsApp. -> (ogg_opus, segundos, waveform)."""
    import av
    with wave.open(TTS_FILE, "wb") as f:
        voice.synthesize_wav(text, f)
    with wave.open(TTS_FILE, "rb") as f:
        samples = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32)
        seconds = f.getnframes() / f.getframerate()
    # la "onda" que dibuja WhatsApp: 64 valores de 0 a 100
    parts = np.array_split(np.abs(samples), 64) if len(samples) >= 64 else [np.zeros(1)] * 64
    peaks = np.array([part.mean() for part in parts])
    waveform = bytes((peaks / (peaks.max() or 1) * 100).astype(np.uint8))
    out_file = io.BytesIO()
    with av.open(TTS_FILE) as src, av.open(out_file, "w", format="ogg") as out:
        stream = out.add_stream("libopus", rate=48000)
        stream.bit_rate = 32000
        stream.layout = "mono"
        resampler = av.AudioResampler(format=stream.format, layout="mono", rate=48000,
                                      frame_size=stream.frame_size or 960)
        for frame in src.decode(audio=0):
            for part in resampler.resample(frame):
                for packet in stream.encode(part):
                    out.mux(packet)
        for part in resampler.resample(None):
            for packet in stream.encode(part):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return out_file.getvalue(), seconds, waveform


def direct_chat(who):
    """(titulo, jid) del chat por la conexion directa, o (None, None). Acepta nombres a medias y numeros."""
    if not (WHATSAPP_DIRECT and whatsapp.ready()):
        return None, None
    try:
        if len(re.sub(r"\D", "", who)) >= 7 and not re.search(r"[a-z]", who.lower()):
            return who, whatsapp.jid_for_number(full_number(who))
        key = comandos._strip(who.lower()).strip()
        return whatsapp.find_chat(who, lambda title: name_score(key, comandos._strip(title.lower())))
    except Exception as e:
        print("WhatsApp directo (buscar chat):", e)
        return None, None


def copy_file(path):
    """Pone un archivo en el portapapeles, como al copiarlo en el Explorador, para pegarlo en un chat."""
    import struct
    import win32clipboard
    data = struct.pack("IiiII", 20, 0, 0, 0, 1) + (os.path.abspath(path) + "\0\0").encode("utf-16-le")
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_HDROP, data)
    finally:
        win32clipboard.CloseClipboard()


def whatsapp_clear_search():
    """Vacia el buscador de WhatsApp para que vuelva a verse la lista de chats completa."""
    try:
        import win32gui
        from pywinauto import Desktop
        window = Desktop(backend="uia").window(handle=win32gui.GetForegroundWindow())
        area = window.rectangle()
        limit = area.left + (area.right - area.left) * 0.45
        box = next((el for el in window.descendants(control_type="Edit")
                    if el.is_visible() and el.rectangle().left < limit), None)
        if box is not None and (box.window_text() or "").strip() and not box.window_text().startswith("Buscar"):
            box.click_input()
            pyautogui.hotkey("ctrl", "a")
            pyautogui.press("backspace")
    except Exception as e:
        print("WhatsApp (limpiar busqueda):", e)


def whatsapp_button(names, bottom=False):
    """Boton visible de WhatsApp cuyo nombre contiene alguno de `names` ("enviar", por ejemplo).

    bottom=True: solo los de la franja de abajo (donde esta el boton verde de enviar) y, de esos,
    el de mas a la derecha; asi no se confunde con un mensaje del chat que diga "enviar".
    """
    import win32gui
    from pywinauto import Desktop
    window = Desktop(backend="uia").window(handle=win32gui.GetForegroundWindow())
    area = window.rectangle()
    found = []
    for el in window.descendants(control_type="Button"):
        try:
            r = el.rectangle()
            text = (el.window_text() or "").strip().lower()
            if not any(n in text for n in names) or not el.is_visible() or not (area.top < r.top < area.bottom):
                continue
            if bottom and r.top < area.bottom - 170:
                continue
            found.append((r.left, el))
        except Exception:
            pass
    if not found:
        return None
    return max(found, key=lambda x: x[0])[1] if bottom else found[0][1]


def whatsapp_audio(name, text):
    """Graba `text` con la voz de Jarvis y lo manda como audio al chat `name` de WhatsApp de escritorio."""
    who = NICKNAMES.get(comandos._strip(name.lower()).strip(), name)
    if not who and wa_messages:
        who = wa_messages[-1][0]
    if not who:
        speak("Tell me who the audio is for.")
        return
    title, jid = direct_chat(who)
    if jid is not None:  # conexion directa: nota de voz de verdad
        try:
            note = make_voice_note(text)
        except Exception as e:
            print("Nota de voz:", e)
            note = None
        if note is not None:
            if not confirm(f"Voice message for {title}, saying: {text}. Send it?"):
                speak("Cancelled.")
                return
            try:
                whatsapp.send_voice(jid, *note)
                speak("Sent.")
                return
            except Exception as e:
                print("WhatsApp directo (nota de voz):", e)
                speak("The direct connection failed, I will use the WhatsApp window.")
    try:
        path = make_audio(text)
        if len(re.sub(r"\D", "", who)) >= 7 and not re.search(r"[a-z]", who.lower()):
            os.startfile(f"whatsapp://send?phone={full_number(who)}")
            time.sleep(WHATSAPP_WAIT)
            shown = who if focus_window("whatsapp") else None
        else:
            shown = whatsapp_open_chat(who)
        if not shown:
            speak(f"I could not find a WhatsApp chat called {who}.")
            return
        copy_file(path)             # como copiar el archivo en el Explorador...
        pyautogui.hotkey("ctrl", "v")  # ...y pegarlo en el chat
        time.sleep(3)
        send = whatsapp_button(("enviar", "send"), bottom=True)
    except Exception as e:
        print("WhatsApp (audio):", e)
        speak("Something went wrong preparing the audio.")
        return
    if send is None:  # no pasa nada: en la pantalla del adjunto, Enter tambien envia
        print("WhatsApp: no encontre el boton de enviar por su nombre; usare Enter")
    ok = confirm(f"Voice message for {shown}, saying: {text}. Send it?")
    if not focus_window("whatsapp"):
        speak("I lost the WhatsApp window, so I did not send it.")
        return
    time.sleep(0.4)
    if ok:
        try:
            (whatsapp_button(("enviar", "send"), bottom=True) or send).click_input()
        except Exception:
            pyautogui.press("enter")
    else:  # cancelar: Escape y luego "Descartar" en la pregunta que sale
        pyautogui.press("esc")
        time.sleep(1)
        try:
            discard = whatsapp_button(("descartar", "discard"))
            if discard is not None:
                discard.click_input()
        except Exception as e:
            print("WhatsApp (descartar):", e)
    time.sleep(0.8)
    whatsapp_clear_search()
    speak("Sent." if ok else "Cancelled.")


def whatsapp_send(name, message):
    """Manda un WhatsApp desde WhatsApp de escritorio; si no puede, responde la notificacion del telefono."""
    key = comandos._strip(name.lower())
    senders = [who for who, _, _ in wa_messages]
    recent = next((who for who in reversed(senders)
                   if key and (key in comandos._strip(who.lower()) or comandos._strip(who.lower()) in key)), None)
    if not name and senders:
        recent = senders[-1]
    who = recent or name
    if not who:
        speak("Tell me who the message is for.")
        return
    who = NICKNAMES.get(comandos._strip(who.lower()).strip(), who)
    message = message[0].upper() + message[1:]
    title, jid = direct_chat(who)
    if jid is not None:  # conexion directa: sin abrir ventanas
        if not confirm(f"Message for {title}: {message}. Send it?"):
            speak("Cancelled.")
            return
        try:
            whatsapp.send_text(jid, message)
            speak("Sent.")
            return
        except Exception as e:
            print("WhatsApp directo (enviar):", e)
            speak("The direct connection failed, I will use the WhatsApp window.")
    shown = None
    if WHATSAPP_FROM_PC:
        try:
            number = None
            if len(re.sub(r"\D", "", who)) >= 7 and not re.search(r"[a-z]", who.lower()):
                number, shown = full_number(who), who          # te dieron el numero directamente
            else:  # se busca el chat (persona o grupo) por su nombre en WhatsApp de escritorio
                try:
                    shown = whatsapp_open_chat(who)
                except Exception as e:
                    print("WhatsApp (buscar chat):", e)
                if shown:
                    pyperclip.copy(message)
                    pyautogui.hotkey("ctrl", "v")
                elif WHATSAPP_USE_CONTACTS:  # ultimo recurso: el numero guardado en el telefono
                    contact = contact_number(who)
                    number, shown = (contact[1], contact[0]) if contact else (None, None)
            if number:
                os.startfile(f"whatsapp://send?phone={number}&text={quote(message)}")  # abre el chat con el texto
                time.sleep(WHATSAPP_WAIT)
        except Exception as e:
            print("WhatsApp:", e)
            shown = None
    if shown:
        ok = confirm(f"Message for {shown}: {message}. Send it?")
        if not focus_window("whatsapp"):
            speak("I lost the WhatsApp window, so I did not send it.")
            return
        time.sleep(0.4)
        if ok:
            pyautogui.press("enter")
        else:
            pyautogui.hotkey("ctrl", "a")
            pyautogui.press("backspace")
        whatsapp_clear_search()
        speak("Sent." if ok else "Cancelled.")
    elif recent:  # ultimo recurso: responder desde la notificacion del telefono
        if confirm(f"Reply to {recent}: {message}. Send it?"):
            speak("Sent." if telefono.send(f"#WAREPLY {recent}|{message}") else "Your phone is not connected.")
        else:
            speak("Cancelled.")
    else:
        speak(f"I could not find a WhatsApp chat called {who}.")


def phone_signal(signal):
    """Avisos de la app del telefono: llamadas y errores."""
    print("Phone:", "#" + signal[:80])
    kind, _, detail = signal.partition(" ")
    if kind == "CALL":
        who = "An unknown number" if detail in ("", "unknown") else detail
        phone_state.update(call="ringing", who=who)
        set_state("awake")
        speak(f"Sir, {who} is calling. Should I answer?")
        set_state("listening", "Answer or decline?")
        text = listen(8)
        if text and phone_state["call"] == "ringing":
            plain = comandos._strip(comandos.clean(strip_wake(text)))
            if re.fullmatch(r"(yes|yeah|yep|si|dale|claro|ok|okay)( please| por favor)?", plain):
                handle("answer call")  # lo obvio va directo; lo demas lo razona la IA
            elif re.fullmatch(r"(no|nope|nah)( thanks| gracias)?", plain):
                handle("end call")
            else:
                run(text)
    elif kind == "CALLSTART":
        phone_state["call"] = "active"
    elif kind == "CALLEND":
        phone_state.update(call=None, who="")
    elif kind in ("WA", "WAD"):  # llego un WhatsApp (WAD: por la conexion directa)
        who, _, text = detail.partition("|")
        who, text = who.strip(), text.strip()
        if any(w == who and t == text and time.time() - when < 120 for w, t, when in wa_messages):
            return  # el mismo mensaje ya llego por el otro camino
        wa_messages.append((who, text, time.time()))
        if WHATSAPP_ANNOUNCE:
            speak(f"Sir, WhatsApp from {who.strip()}.")
    elif kind == "APPS":  # la app pide la lista para su menu
        skip = r"uninstall|desinstalar|readme|license|documentation|release notes|\bhelp\b|\bayuda\b"
        names = sorted({n for n in APP_DISPLAY.values() if not re.search(skip, n, re.I)}, key=str.lower)
        telefono.send("#APPS " + "|".join(n.replace("|", " ") for n in names))
    elif kind == "ICONS":  # la app pide los logos que le faltan
        threading.Thread(target=send_icons, args=([k for k in detail.split(",") if k],), daemon=True).start()
    elif kind in ("OPEN", "PLAYING", "ERROR"):
        S["phone"] = True  # la respuesta va al telefono
        try:
            if kind == "OPEN":
                got = open_app(detail.lower())
                speak(f"Opening {APP_DISPLAY.get(got, got)}." if got else f"I could not open {detail}.")
            elif kind == "PLAYING":
                title, _, artist = detail.partition("|")
                speak(f"Playing {title} by {artist}." if artist else f"Playing {title}.")
            else:
                speak(detail)
        finally:
            S.pop("phone", None)


def brain():
    try:
        import pythoncom  # necesario para controlar el volumen de Spotify
        pythoncom.CoInitialize()
    except Exception:
        pass
    while True:
        try:
            if not telefono.signals.empty():
                phone_signal(telefono.signals.get())
            elif not telefono.inbox.empty():
                text = telefono.inbox.get()
                print("Phone:", text)
                S["phone"] = True
                set_state("awake")
                try:
                    run(text)
                finally:
                    S.pop("phone", None)
            elif not events.empty():
                while not events.empty():
                    events.get()
                set_state("awake")
                conversation()
            elif WAKE_ENABLED:
                text = listen(idle=True)
                if text and has_wake(text):
                    set_state("awake")
                    rest = strip_wake(text)
                    conversation(rest if rest else None)
                elif text is False:
                    time.sleep(5)  # sin internet: espera antes de volver a intentar
            else:
                time.sleep(0.1)
        except Exception as e:
            print("Error:", e)
            time.sleep(1)
        if events.empty():
            set_state("sleep")


if __name__ == "__main__":
    root = ui.create(S, events)
    threading.Thread(target=load_apps, daemon=True).start()
    threading.Thread(target=warm_up, daemon=True).start()
    threading.Thread(target=mic_loop, daemon=True).start()
    if PHONE_ENABLED:
        telefono.start(PHONE_PORT)
    if WHATSAPP_DIRECT:
        def wa_message(who, text, is_group, jid):
            if not is_group:  # los grupos no se anuncian
                telefono.signals.put(f"WAD {who}|{text.replace(chr(10), ' ')}")
        whatsapp.start(HERE, wa_message)
    threading.Thread(target=brain, daemon=True).start()
    root.mainloop()
