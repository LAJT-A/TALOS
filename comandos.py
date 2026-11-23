"""Convierte lo que dices, en español o en inglés, en una orden en inglés para Jarvis.

Si la frase no es una orden conocida, se devuelve limpia y Jarvis se la pasa a la IA.
"""
import re
import unicodedata

PUNCT = r"[¿¡?!.,;:\"]"
POLITE = (r"^(hey |ok |okay |oye |jarvis )?(can you|could you|would you|will you|please|i want you to|i need you to"
          r"|puedes|podrias|me puedes|me podrias|quiero que|necesito que|por favor"
          r"|busca y|buscar y|search and|find and|search for and)( please| por favor)? ")
POLITE_END = r"( please| por favor| for me| now| ahora| ya)+$"

NUMS = {"un": 1, "uno": 1, "una": 1, "one": 1, "dos": 2, "two": 2, "tres": 3, "three": 3,
        "cuatro": 4, "four": 4, "cinco": 5, "five": 5, "diez": 10, "ten": 10, "quince": 15,
        "fifteen": 15, "veinte": 20, "twenty": 20, "treinta": 30, "thirty": 30}
UNITS = {"segundo": "second", "minuto": "minute", "hora": "hour",
         "second": "second", "minute": "minute", "hour": "hour"}
KEYS = {"espacio": "space", "tabulador": "tab", "borrar": "backspace", "suprimir": "delete",
        "mayusculas": "shift", "arriba": "up", "abajo": "down", "izquierda": "left",
        "derecha": "right", "intro": "enter", "entrar": "enter", "mas": "plus"}

MUSIC_WORDS = r"(spotify|music|musica|song|cancion|tema)"

# (patron sobre el texto sin acentos, orden en ingles). Se prueban en este orden.
PHONE = r" ((en|on|in|del|de|from|a|to) (el |mi |my |the )?|al )(celular|telefono|phone|cel|movil)$"

FIXED = [
    # --- WhatsApp ---
    (r"^(lee|leeme|leelo|lee me|read|read me)( el| los| the| my| mis| me)*( ultimo| ultimos| last| latest| new| nuevos?)?"
     r" ?(mensajes?|whatsapps?|wasaps?|messages?|it|texts?)?$"
     r"|^que (me )?(dice|dijo|escribio|escribieron|mandaron|mando)$|^(what does it say|what did (he|she|they) say)$",
     "read messages"),
    # --- llamadas del telefono ---
    (r"^(contesta|contestar|contestala|responde|respondela|atiende|atender|atiendela|answer|pick up|pick it up)"
     r"( (la|el|the|that|esa))?( llamada| telefono| call| phone| it)?$", "answer call"),
    (r"^(cuelga|colgar|cuelgala|rechaza|rechazar|rechazala|hang up|decline|reject)( (la|the|that|esa))?( llamada| call| it)?$"
     r"|^(end|termina|corta) (la |the )?(llamada|call)$", "end call"),
    # --- Spotify ---
    (r"^(pause|pausa|pausar|pausala|pausalo|(pon|ponle|ponme|dale|ponla|ponlo) (una |la )?pausa|stop|para|parar|parala|deten|detener|detenla)( a| to)?( (the|la|el|a|it))?( music| musica| song| cancion| spotify)?$",
     "pause music"),
    (r"^(play|resume|continue|unpause|reanuda|reanudar|continua|continuar|dale play|quita la pausa|reproduce|pon)"
     r"( (the|la|el))?( music| musica| song| cancion| spotify)$", "resume music"),
    (r"^(play|resume|continue|unpause|reanuda|reanudar|continua|continuar|dale play|quita la pausa)$", "resume music"),
    (r"^(next|skip|siguiente|proxima|pasala|saltala)( (the |this |la |esta )?(song|track|one|cancion|tema))?( please| por favor)?$"
     r"|^(play|go to|pon) (the |la )?(next|siguiente) (song|track|cancion|tema)$"
     r"|\b(pasa|salta|cambia|adelanta)( la| el| de| esta)? (cancion|tema|musica|rola)\b|\b(cancion|tema) siguiente\b", "next song"),
    (r"^(previous|last|anterior)( (the )?(song|track|one|cancion|tema))?$"
     r"|^(play|go to|go back to) the (previous|last) (song|track)$|^go back (a|one) (song|track)$"
     r"|\b(cancion|tema) anterior\b|\b(vuelve|regresa|devuelvete|pon|ve)( a)? la (cancion |del? )?anterior\b|la de antes",
     "previous song"),
    (r"what('s| is) (playing|this song)|what song is (this|playing)|which song is (this|playing)"
     r"|que (cancion|tema) (es|esta sonando|suena)|que (esta sonando|suena)", "what is playing"),
    (r"^(mute|silence|silencia|mutea|quitale el sonido a) (spotify|the music|la musica)$", "mute spotify"),
    (r"^(unmute|desmutea|devuelvele el sonido a) (spotify|the music|la musica)$", "unmute spotify"),
    (r"\b(turn up|raise|increase|louder|sube|subele|subir|aumenta|aumentale|mas alto)\b.*\b" + MUSIC_WORDS + r"\b"
     r"|\b" + MUSIC_WORDS + r"\b.*\b(volume up|louder|up|mas alto)$", "spotify volume up"),
    (r"\b(turn down|lower|decrease|quieter|softer|baja|bajale|bajar|reduce|disminuye|mas bajo)\b.*\b" + MUSIC_WORDS + r"\b"
     r"|\b" + MUSIC_WORDS + r"\b.*\b(volume down|quieter|softer|down|mas bajo)$", "spotify volume down"),
    # --- modos de juego (game night primero, porque "gaming mode 1" tambien dice gaming mode) ---
    (r"game ?night|noche de juegos?|gaming mode (number |numero )?(1|one|uno|won)\b|modo (de )?juegos? (1|uno)\b",
     "active game night"),
    (r"\b(activ\w*|enable|turn on|start|enciende|pon|ponme|inicia)\b.*\b(gamer|gaming|game|juego|juegos)\b.*\b(mode|modo)\b"
     r"|\b(activ\w*|enable|turn on|start|enciende|pon|ponme|inicia)\b.*\b(mode|modo|moto)\b.*\b(gamer|gaming|game|juego|juegos)\b"
     r"|^(the )?(gaming|gamer|game) mode$|^modo (gamer|juego|gaming)$", "active gamer mode"),
    # --- Jarvis ---
    (r"^(exit|quit|bye|goodbye|salir|sal|adios|cierrate|apagate|hasta luego)$", "exit"),
    # --- sistema ---
    (r"captura de pantalla|(toma|haz|saca) una captura", "screenshot"),
    (r"^(cierra|cerrar) (la |esta )?ventana$", "close window"),
    (r"^(copia|copiar)( esto)?$", "copy"), (r"^(pega|pegar)( esto)?$", "paste"),
    (r"^(corta|cortar)( esto)?$", "cut"), (r"^selecciona(r)? todo$", "select all"),
    (r"^(deshaz|deshacer)$", "undo"), (r"^(rehaz|rehacer)$", "redo"),
    (r"^(guarda|guardar)( esto| el archivo)?$", "save"),
    (r"^(actualiza|recarga)( la pagina)?$", "refresh"), (r"^(ve hacia atras|regresa|atras)$", "go back"),
    (r"^cambia de ventana$", "switch window"), (r"^(muestra|ver) el escritorio$", "show desktop"),
    (r"^minimiza(r)?( la ventana)?$", "minimize"), (r"^maximiza(r)?( la ventana)?$", "maximize"),
    (r"(sube|subele|aumenta).*volumen", "volume up"), (r"(baja|bajale|reduce).*volumen", "volume down"),
    (r"^(silencia|silencio|quita el sonido)$", "mute"),
    (r"^(desplazate (hacia )?abajo|scroll down)$", "scroll down"),
    (r"^(desplazate (hacia )?arriba|scroll up)$", "scroll up"),
    (r"que hora es|dime la hora", "what time"), (r"que fecha es|que dia es( hoy)?", "what date"),
    (r"el clima|que tiempo hace", "weather"),
    (r"nueva pestana", "new tab"), (r"(cierra|cerrar) (la )?pestana", "close tab"),
    (r"siguiente pestana", "next tab"),
]

# Ordenes con algo detras: (patron, prefijo en ingles). El resto se copia tal como lo dijiste.
PREFIX = [
    (r"^(pon|reproduce|busca|toca|play) (.+) (en|on) spotify$", None),  # se trata aparte
    (r"^(haz |dale )?doble cli(c|ck)( en| a)? ", "double click "),
    (r"^(haz |dale )?cli(c|ck) derecho( en| a)? ", "right click "),
    (r"^(haz |dale )?cli(c|ck)( en| a)? ", "click "),
    (r"^pulsa en ", "click "),
    (r"^(escribe|escribir|teclea) ", "type "),
    (r"^(abre|abrir|abreme|inicia|ejecuta)( el| la| los| las| mi| mis)? ", "open "),
    (r"^(cierra|cierrame|cerrar|cierre|close|quit|kill|mata)( el| la| los| las| mi| mis| the)? ", "close "),
    (r"^(busca|buscar|googlea)( en google)? ", "search "),
    (r"^(pon|ponme|poner|ponerme|reproduce|reproducir|toca)( la cancion| la musica| musica de| musica)? ", "play "),
    (r"^(anota|apunta|nota) ", "note "),
    (r"^(cambia a|ve a) ", "switch to "),
]


def _strip(text):
    """Quita acentos letra por letra, sin cambiar la longitud."""
    return "".join(unicodedata.normalize("NFD", ch)[0] for ch in text)


def clean(text):
    """Minusculas, sin signos y sin espacios dobles. Conserva acentos."""
    text = unicodedata.normalize("NFC", text.lower())
    return re.sub(r"\s+", " ", re.sub(PUNCT, " ", text)).strip()


def _plain_name(name):
    """True si parece solo el nombre de un chat. Si trae instrucciones ("mandando saludos y contando"),
    la frase no es una orden directa: que la IA la entienda y redacte el mensaje."""
    words = [w for w in name.split()
             if w not in ("fernando", "armando", "orlando", "rolando", "hernando", "normando", "segundo", "facundo")]
    return len(name.split()) <= 5 and not any(
        re.fullmatch(r"\w+[ae]ndo|\w+[ae]ndoles?|y|e|donde|para|pero|con|sobre|and|about|saying|telling", w)
        for w in words)


def to_command(text):
    """Devuelve la orden en ingles, o el texto limpio si no es una orden."""
    m = re.match(r"\s*whatsapp (reply|audio)(?: to ([^:]*))?:\s*(.+?)\s*$", text, flags=re.I)
    if m:  # orden ya armada (la escribe la IA): el mensaje se deja tal cual
        kind, name = m.group(1).lower(), (m.group(2) or "").strip().lower()
        return f"whatsapp {kind} to {name}: {m.group(3)}" if name else f"whatsapp {kind}: {m.group(3)}"
    original = clean(text)
    while True:  # "can you open spotify" = "open spotify"
        m = re.match(POLITE, _strip(original))
        if not m or m.end() >= len(original):
            break
        original = original[m.end():].strip()
    original = re.sub(POLITE_END, "", original).strip() or original
    m = re.search(r"\b(?:volumen|volume)\b.*\b(?:cel|celular|telefono|phone|movil)\b\D*(\d{1,3})", _strip(original))
    if m:  # "pon el volumen del celular en 30"
        return f"phone volume {min(100, int(m.group(1)))}"
    # Mensajes y audios de WhatsApp: siempre los entiende y redacta la IA, nunca una regla fija.
    if re.search(r"^(respondele|respondela|contestale|escribele|escribeles|dile|diles|mandale|mandales|enviale|enviales"
                 r"|grabale|grabales|avisale|avisales)\b"
                 r"|\b(mensaje|mensajes|whatsapp|wasap|nota de voz|notas de voz|voice message|voice note)\b"
                 r"|\b(un|una|an?) audio\b"
                 r"|^(escribe|manda|envia|responde|contesta|send|text|tell|reply|message)\b.*\b(grupo|group|que|that)\b.+",
                 _strip(original)) and not re.search(r"\b(llamada|call)\b", _strip(original)) \
            and not re.match(r"^(lee|leeme|leelo|read|que (me )?(dice|dijo)|abre|abrir|open|cierra|cerrar|close)\b", _strip(original)):
        return original
    m = re.match(r"^(?:pon|ponme|reproduce|toca|play|busca|buscame) (?:en|on|in) (?:mi |el |my |the )?"
                 r"(?:cel|celular|telefono|phone|movil) (.+)$", _strip(original))
    if m:  # "pon en mi cel almohada de jose jose"
        song = re.sub(r"( y| and)? (ponle play|ponla|ponlo|dale play|play it)$", "", original[m.start(1):])
        return "phone play " + song
    m = re.search(PHONE, _strip(original))  # "siguiente cancion en el celular"
    if m and m.start() > 0:
        level = re.search(r"\b(?:volumen|volume|vol)\b.*?(\d{1,3})|(\d{1,3})\s*(?:%|por ciento|percent).*\b(?:volumen|volume)\b",
                          _strip(original[:m.start()]))
        if level:
            return f"phone volume {min(100, int(level.group(1) or level.group(2)))}"
        inner = to_command(original[:m.start()])
        if re.fullmatch(r"(pon |ponle |dale )?(play|reproducir)", _strip(original[:m.start()])):
            inner = "resume music"
        if inner.startswith("play ") and not inner.endswith(" on youtube"):
            return "phone play " + re.sub(r" on spotify$", "", inner[5:])
        if inner in ("pause music", "resume music", "next song", "previous song"):
            return "phone " + inner
        if inner in ("volume up", "volume down", "spotify volume up", "spotify volume down"):
            return "phone volume " + inner.split()[-1]
    words = original.split()  # "ponle pausa ponle pausa" = "ponle pausa"
    half = len(words) // 2
    if half and len(words) % 2 == 0 and words[:half] == words[half:]:
        original = " ".join(words[:half])
    plain = _strip(original)

    m = re.search(r"(?:temporizador|alarma|recuerdame|avisame|timer|remind me).*?(\d+|"
                  + "|".join(NUMS) + r")\s*(segundo|minuto|hora|second|minute|hour)", plain)
    if m:
        n = m.group(1)
        return f"timer {NUMS.get(n, n)} {UNITS[m.group(2)]}"

    m = re.search(r"(?:volumen|volume)\s+(?:de |del |de la |of |on |for )?(?:spotify|the music|la musica|musica|music)"
                  r"\s+(?:al?|en|to|at)?\s*(\d{1,3})", plain) \
        or re.search(r"(?:spotify|music)\s+(?:volume\s+(?:al?\s+|to\s+|at\s+)?|(?:al?|to|at)\s+)(\d{1,3})", plain)
    if m:
        return f"spotify volume {min(100, int(m.group(1)))}"

    m = re.match(r"^(presiona|pulsa|oprime|aprieta) (la tecla )?(.+)$", plain)
    if m:
        return "press " + " ".join(KEYS.get(k, k) for k in m.group(3).split())

    # "y ponle play", "and play it" al final no cambian la orden
    plain2 = re.sub(r" ((y|and) )?(ponle play|ponla|ponlo|dale play|reproducela|reproducelo|play it)$", "", plain)
    plain2 = re.sub(r" (y|and) (dale|play)$", "", plain2)
    original = original[:len(plain2)]
    plain = plain2
    # "busca en Spotify" sin decir que: Jarvis pregunta que poner
    if re.fullmatch(r"(abre |open )?(busca|buscame|buscar|search|search for|find|pon|ponme|play|reproduce)"
                    r"( algo)?( en| on| in)?( el)? spotify|(abre|open) spotify (y|and) (busca|buscame|search|pon|ponme|play)( algo)?",
                    plain):
        return "spotify ask"
    plain2 = re.sub(r"^(abre|open) spotify (y|and) ", "", plain)  # "abre spotify y busca X"
    if plain2 != plain:
        original, plain = original[len(plain) - len(plain2):], plain2
        if not re.search(r"\b(spotify|youtube)$", plain):
            plain, original = plain + " en spotify", original + " en spotify"
    plain2 = re.sub(r"^(busca|buscame|buscar|pon|ponme|reproduce) en el spotify", r"\1 en spotify", plain)
    original, plain = original[len(plain) - len(plain2):] if len(plain2) > len(plain) else original.replace(" en el spotify", " en spotify", 1), plain2
    plain = re.sub(r"^buscame ", "busca ", plain)
    original = re.sub(r"^búscame ", "busca ", original)
    m = re.match(r"^(?:busca|buscar|search|search for|find|pon|ponme|play|reproduce)(?: en| on| in)? (spotify|youtube)"
                 r"(?: for| a)? (.+)$", plain)  # "busca en Spotify la mentira"
    if m:
        return "play " + original[m.start(2):m.end(2)] + " on " + m.group(1)
    m = re.match(r"^(?:ponle play a|dale play a|play me) (.+)$", plain)
    if m:
        if re.fullmatch(r"(la |the |el )?(musica|music|cancion|song|spotify)", m.group(1)):
            return "resume music"
        return "play " + original[m.start(1):m.end(1)]
    m = re.match(r"^(?:pon|ponme|poner|ponerme|reproduce|reproducir|busca|buscar|search for|search|find|toca|play) (.+) (?:en|on|in) (spotify|youtube)$", plain)
    if m:
        return "play " + original[m.start(1):m.end(1)] + " on " + m.group(2)

    for pattern, command in FIXED:
        if re.search(pattern, plain):
            return command

    for pattern, command in PREFIX:
        m = re.match(pattern, plain)
        if m and command:
            return command + original[m.end():]
    return original


ENGLISH = r"^(open|search|play|type|press|click|double click|right click|switch to|note|timer|scroll)\b"


CANONICAL = {command for _, command in FIXED}


def is_command(text):
    """True si la frase parece una orden (sirve para elegir entre ingles y español)."""
    command = to_command(text)
    return (command != clean(text) or command in CANONICAL
            or re.match(ENGLISH, command) is not None or command.startswith(("spotify volume", "phone ", "whatsapp reply", "whatsapp audio")))
