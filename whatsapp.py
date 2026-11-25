"""Conexión directa con WhatsApp mediante neonize (whatsmeow).

Funciona como un dispositivo vinculado más de tu cuenta, igual que WhatsApp Web:
la primera vez se escanea un código QR y después la sesión queda guardada en
whatsapp.db. Manda texto y notas de voz en menos de un segundo, sin tocar la
pantalla, y avisa de los mensajes que llegan.

Si neonize no está instalado o no hay sesión, ready() devuelve False y TALOS usa
el método de siempre (la ventana de WhatsApp de escritorio).
"""
import os
import threading
import time

state = {"status": "off", "error": ""}  # off, qr, connected, logged_out, error
_client = None
_lock = threading.Lock()
_chats = {"time": 0.0, "list": []}       # (nombre, jid) de contactos y grupos
_seen = {}                               # jid -> nombre de quien escribio hace poco


def ready():
    """True si la conexión directa está lista para enviar."""
    return _client is not None and state["status"] == "connected"


def start(folder, on_message, on_status=print):
    """Conecta en segundo plano. on_message(dict) por cada mensaje que llega (ver _incoming)."""
    try:
        import neonize  # noqa: F401  (solo comprueba que esta instalado)
    except ImportError:
        on_status("WhatsApp directo: falta instalar neonize (instalar_whatsapp.bat)")
        return False
    threading.Thread(target=_run, args=(folder, on_message, on_status), daemon=True,
                     name="whatsapp").start()
    return True


def _run(folder, on_message, on_status):
    global _client
    import logging
    from neonize.client import NewClient
    from neonize.utils.log import log as neonize_log
    # solo avisos y errores: sin esto la consola se llena con la sincronizacion del historial
    for logger in (neonize_log, logging.getLogger("whatsmeow"), logging.getLogger("Whatsmeow")):
        logger.setLevel(logging.WARNING)
    from neonize.events import ConnectedEv, LoggedOutEv, MessageEv, PairStatusEv

    db = os.path.join(folder, "whatsapp.db")
    qr_file = os.path.join(folder, "whatsapp_qr.png")
    while True:
        client = NewClient(db, uuid="talos")

        def on_qr(_, data):
            state["status"] = "qr"
            try:
                import segno
                segno.make_qr(data).save(qr_file, scale=10, border=3)
                os.startfile(qr_file)
            except Exception as e:
                on_status(f"WhatsApp directo: no pude mostrar el QR ({e})")
            on_status("WhatsApp directo: escanea el QR desde WhatsApp > Dispositivos vinculados > Vincular dispositivo")

        client.event.qr(on_qr)

        @client.event(PairStatusEv)
        def _paired(_, ev):
            on_status("WhatsApp directo: vinculado")

        @client.event(ConnectedEv)
        def _connected(_, ev):
            state["status"] = "connected"
            try:
                os.remove(qr_file)
            except OSError:
                pass
            on_status("WhatsApp directo: conectado")

        @client.event(LoggedOutEv)
        def _logged_out(_, ev):
            state["status"] = "logged_out"
            on_status("WhatsApp directo: la sesión se cerró desde el teléfono; borra whatsapp.db para vincular de nuevo")

        @client.event(MessageEv)
        def _message(cl, ev):
            try:
                _incoming(cl, ev, on_message)
            except Exception as e:
                on_status(f"WhatsApp directo (mensaje): {e}")

        with _lock:
            _client = client
        try:
            client.connect()  # se queda aquí mientras dure la conexión
        except Exception as e:
            state.update(status="error", error=str(e))
            on_status(f"WhatsApp directo: {e}")
        if state["status"] == "logged_out":
            return
        state["status"] = "off"
        time.sleep(30)  # se cayó la conexión: reintenta


def _text_of(msg):
    """Texto legible de un mensaje, o None si no vale la pena avisarlo."""
    if msg.conversation:
        return msg.conversation
    if msg.extendedTextMessage.text:
        return msg.extendedTextMessage.text
    if msg.HasField("audioMessage"):
        return "sent a voice note" if msg.audioMessage.PTT else "sent an audio"
    if msg.HasField("imageMessage"):
        return "sent a photo" + (f": {msg.imageMessage.caption}" if msg.imageMessage.caption else "")
    if msg.HasField("videoMessage"):
        return "sent a video" + (f": {msg.videoMessage.caption}" if msg.videoMessage.caption else "")
    if msg.HasField("stickerMessage"):
        return "sent a sticker"
    if msg.HasField("documentMessage"):
        return "sent a document"
    return None


def _jid_text(jid):
    return f"{jid.User}@{jid.Server}"


def _incoming(cl, ev, on_message):
    """Pasa a TALOS cada mensaje que llega como un dict:
    who (quien, para avisar), name (nombre corto), text (descripcion legible), raw (el texto tal cual,
    o "" si es foto/audio...), is_group, chat, sender, from_me."""
    src = ev.Info.MessageSource
    if src.Chat.Server in ("broadcast", "newsletter"):
        return
    raw = ev.Message.conversation or ev.Message.extendedTextMessage.text or ""
    if src.IsFromMe and not raw.lstrip().startswith("."):
        return  # lo tuyo solo interesa si es una orden para el bot (".jarvis ...", ".stop")
    text = _text_of(ev.Message)
    if not text:
        return
    name = _name_of_contact(cl, src.Sender) or ev.Info.Pushname or src.Sender.User
    if src.IsGroup:
        group = _name_of_group(cl, src.Chat)
        who = f"{ev.Info.Pushname or name} in {group}"
        _seen[_jid_text(src.Chat)] = (group, src.Chat)
    else:
        who = name
        if not src.IsFromMe:
            _seen[_jid_text(src.Chat)] = (who, src.Chat)
    on_message({"who": who, "name": (ev.Info.Pushname or name).split()[0] if (ev.Info.Pushname or name) else "",
                "text": text, "raw": raw, "is_group": src.IsGroup, "chat": src.Chat,
                "sender": src.Sender, "from_me": src.IsFromMe})


def _name_of_contact(cl, jid):
    try:
        info = cl.contact.get_contact(jid)
        return info.FullName or info.FirstName or info.PushName or info.BusinessName or None
    except Exception:
        return None


def _name_of_group(cl, jid):
    for name, chat in chats():
        if chat.User == jid.User and chat.Server == jid.Server:
            return name
    try:
        return cl.get_group_info(jid).GroupName.Name or "a group"
    except Exception:
        return "a group"


def chats(refresh=False):
    """(nombre, jid) de tus contactos guardados y tus grupos. Se refresca cada 10 minutos."""
    client = _client
    if client is None:
        return []
    if not refresh and _chats["list"] and time.time() - _chats["time"] < 600:
        return _chats["list"]
    found = []
    try:
        for group in client.get_joined_groups():
            if group.GroupName.Name:
                found.append((group.GroupName.Name, group.JID))
    except Exception as e:
        print("WhatsApp directo (grupos):", e)
    try:
        for contact in client.contact.get_all_contacts():
            info = contact.Info
            for name in {info.FullName, info.FirstName, info.PushName, info.BusinessName}:
                if name:
                    found.append((name, contact.JID))
    except Exception as e:
        print("WhatsApp directo (contactos):", e)
    found += [(name, jid) for name, jid in _seen.values()]
    _chats.update(time=time.time(), list=found)
    return found


def find_chat(name, score):
    """El chat que mejor coincide con `name`. score(nombre) da menos = mejor, None = no es. -> (titulo, jid)."""
    best = None
    for title, jid in chats():
        s = score(title)
        if s is not None and (best is None or s < best[0]):
            best = (s, title, jid)
    if best is None:  # quizas es un grupo o contacto nuevo: vuelve a leer la lista
        for title, jid in chats(refresh=True):
            s = score(title)
            if s is not None and (best is None or s < best[0]):
                best = (s, title, jid)
    return (best[1], best[2]) if best else (None, None)


def key_of(jid):
    """Texto unico de un JID, para usarlo como clave."""
    return _jid_text(jid)


def jid_for_number(number):
    """JID de un número con código de país (solo dígitos)."""
    from neonize.utils import build_jid
    return build_jid(number)


def send_text(jid, text):
    _client.send_message(jid, text)


def send_voice(jid, ogg_opus, seconds, waveform=b""):
    """Manda una nota de voz (audio OGG con Opus), con el micrófono verde de WhatsApp."""
    from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import AudioMessage, Message
    from neonize.utils.enum import MediaType
    up = _client.upload(ogg_opus, MediaType.MediaAudio)
    audio = AudioMessage(
        URL=up.url,
        directPath=up.DirectPath,
        mediaKey=up.MediaKey,
        fileEncSHA256=up.FileEncSHA256,
        fileSHA256=up.FileSHA256,
        fileLength=up.FileLength,
        mimetype="audio/ogg; codecs=opus",
        seconds=max(1, int(round(seconds))),
        PTT=True,
    )
    if waveform:
        audio.waveform = waveform
    _client.send_message(jid, Message(audioMessage=audio))
