"""Conexión directa con WhatsApp mediante neonize (whatsmeow).

Funciona como un dispositivo vinculado más de tu cuenta, igual que WhatsApp Web:
la primera vez se escanea un código QR y después la sesión queda guardada en
whatsapp.db. Manda texto y notas de voz en menos de un segundo, sin tocar la
pantalla, y avisa de los mensajes que llegan.

Si neonize no está instalado o no hay sesión, ready() devuelve False y TALOS usa
el método de siempre (la ventana de WhatsApp de escritorio).
"""
import os
import re
import sqlite3
import threading
import time

state = {"status": "off", "error": ""}  # off, qr, connected, logged_out, error
_client = None
_lock = threading.Lock()
_chats = {"time": 0.0, "list": []}       # (nombre, jid) de contactos y grupos
_seen = {}                               # jid -> nombre de quien escribio hace poco
bot_ids = set()                          # IDs de los mensajes que mando el bot (para saber si le responden a el)
owner = {"name": "me"}                   # como se llama el dueño en el archivo de mensajes
_db = {"conn": None, "lock": threading.Lock()}


# ======================= ARCHIVO DE MENSAJES =======================
# Guarda en whatsapp_mensajes.db el texto de los mensajes (los que llegan, los del historial que manda
# el telefono al vincular y los del bot), para que el bot pueda ver mensajes viejos y su contexto.

def _archive_open(folder):
    conn = sqlite3.connect(os.path.join(folder, "whatsapp_mensajes.db"), check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS msgs (chat TEXT, id TEXT, sender TEXT, name TEXT, ts INTEGER,"
                 " from_me INTEGER, text TEXT, PRIMARY KEY (chat, id))")
    conn.execute("CREATE INDEX IF NOT EXISTS by_time ON msgs (chat, ts)")
    conn.commit()
    _db["conn"] = conn


def _archive_add(rows):
    if not rows:
        return
    with _db["lock"]:
        conn = _db["conn"]
        if conn is not None:
            conn.executemany("INSERT OR IGNORE INTO msgs VALUES (?,?,?,?,?,?,?)", rows)
            conn.commit()


def _query(sql, args=()):
    with _db["lock"]:
        conn = _db["conn"]
        return conn.execute(sql, args).fetchall() if conn is not None else []


def _seconds(ts):
    ts = int(ts or 0)
    return ts // 1000 if ts > 10_000_000_000 else ts


def lines(rows):
    """Filas del archivo como texto: "[25/11 18:12] Gabo: hola"."""
    return "\n".join(f"[{time.strftime('%d/%m/%y %H:%M', time.localtime(ts))}] {name}: {text}"
                     for ts, name, text in rows)


def around(chat_key, msg_id, before=15, after=8):
    """Los mensajes alrededor de uno (por su ID). [] si no esta en el archivo."""
    hit = _query("SELECT ts FROM msgs WHERE chat=? AND id=?", (chat_key, msg_id))
    if not hit:
        return []
    ts = hit[0][0]
    older = _query("SELECT ts, name, text FROM msgs WHERE chat=? AND ts<=? ORDER BY ts DESC LIMIT ?",
                   (chat_key, ts, before + 1))
    newer = _query("SELECT ts, name, text FROM msgs WHERE chat=? AND ts>? ORDER BY ts LIMIT ?",
                   (chat_key, ts, after))
    return list(reversed(older)) + newer


def recent(chat_key, n=12):
    return list(reversed(_query("SELECT ts, name, text FROM msgs WHERE chat=? ORDER BY ts DESC LIMIT ?",
                                (chat_key, n))))


def search(chat_key, words, limit=10):
    """Mensajes del chat que contienen alguna de esas palabras, con 2 mensajes de contexto a cada lado."""
    found, seen = [], set()
    for word in words[:6]:
        for ts, mid in _query("SELECT ts, id FROM msgs WHERE chat=? AND lower(text) LIKE ? ORDER BY ts DESC LIMIT ?",
                              (chat_key, f"%{word.lower()}%", limit)):
            if mid in seen:
                continue
            seen.add(mid)
            found.append((ts, around(chat_key, mid, before=2, after=2)))
    found.sort(key=lambda x: x[0])
    return [rows for _, rows in found[-limit:]]


def since(chat_key, ts, limit=600):
    """Mensajes del chat despues de ese momento (los mas viejos primero)."""
    return _query("SELECT ts, name, text FROM msgs WHERE chat=? AND ts>? ORDER BY ts LIMIT ?",
                  (chat_key, int(ts), limit))


def all_messages(chat_key, limit=4000):
    return list(reversed(_query("SELECT ts, name, text FROM msgs WHERE chat=? ORDER BY ts DESC LIMIT ?",
                                (chat_key, limit))))


def count(chat_key=None):
    if chat_key:
        return _query("SELECT count(*) FROM msgs WHERE chat=?", (chat_key,))[0][0]
    return _query("SELECT count(*) FROM msgs")[0][0]



def ready():
    """True si la conexión directa está lista para enviar."""
    return _client is not None and state["status"] == "connected"


_started = [time.time()]


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
    from neonize.events import ConnectedEv, HistorySyncEv, LoggedOutEv, MessageEv, PairStatusEv
    from neonize.proto.waCompanionReg.WACompanionReg_pb2 import DeviceProps

    db = os.path.join(folder, "whatsapp.db")
    qr_file = os.path.join(folder, "whatsapp_qr.png")
    _archive_open(folder)
    # al vincular, pide al telefono el historial completo (hasta un año) para el archivo de mensajes
    props = DeviceProps(os="TALOS", platformType=DeviceProps.SAFARI, requireFullSync=True,
                        historySyncConfig=DeviceProps.HistorySyncConfig(fullSyncDaysLimit=365,
                                                                        supportGroupHistory=True))
    while True:
        client = NewClient(db, uuid="talos", props=props)

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
        def _logged_out(cl, ev):
            state["status"] = "logged_out"
            on_status("WhatsApp directo: cerraste la sesión desde el teléfono; preparo un QR nuevo")
            try:
                cl.disconnect()
            except Exception:
                pass

        @client.event(HistorySyncEv)
        def _history(cl, ev):
            try:
                n = _history_rows(cl, ev)
                if n:
                    on_status(f"WhatsApp directo: historial +{n} mensajes (total {count()})")
            except Exception as e:
                on_status(f"WhatsApp directo (historial): {e}")

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
        if state["status"] == "logged_out":  # vincular de nuevo: la sesion vieja se guarda aparte
            time.sleep(2)
            try:
                os.replace(db, db.replace(".db", time.strftime("_vieja_%Y%m%d_%H%M%S.db")))
            except OSError as e:
                on_status(f"WhatsApp directo: no pude apartar whatsapp.db ({e}); ciérralo y bórralo a mano")
                return
            state["status"] = "off"
            continue
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


def _history_rows(cl, ev):
    """Guarda en el archivo los mensajes del historial que manda el telefono."""
    from neonize.proto.Neonize_pb2 import JID
    names, rows = {}, []
    for conv in ev.Data.conversations:
        chat = conv.ID
        for item in conv.messages:
            w = item.message
            text = _text_of(w.message)
            if not text or not w.key.ID:
                continue
            me = w.key.fromMe
            sender = "" if me else (w.key.participant or w.participant or chat)
            if me:
                name = owner["name"]
            else:
                if sender not in names:
                    user, _, server = sender.partition("@")
                    names[sender] = _name_of_contact(cl, JID(User=user, Server=server)) or w.pushName or user
                name = names[sender]
            rows.append((chat, w.key.ID, sender, name, _seconds(w.messageTimestamp), int(me), text))
    _archive_add(rows)
    return len(rows)


def _incoming(cl, ev, on_message):
    """Pasa a TALOS cada mensaje que llega como un dict:
    who (quien, para avisar), name (nombre corto), text (descripcion legible), raw (el texto tal cual,
    o "" si es foto/audio...), is_group, chat, sender, from_me."""
    src = ev.Info.MessageSource
    if src.Chat.Server in ("broadcast", "newsletter"):
        return
    msg = ev.Message
    media = ("image" if msg.HasField("imageMessage") else "sticker" if msg.HasField("stickerMessage")
             else "video" if msg.HasField("videoMessage") else None)
    raw = (msg.conversation or msg.extendedTextMessage.text or msg.imageMessage.caption
           or msg.videoMessage.caption or "")
    quoted, quoted_kind, quoted_text, quoted_id = _quoted(msg)
    text = _text_of(ev.Message)
    if not text:
        return
    contact = None if src.IsFromMe else _saved_name(cl, src)  # en grupos el remitente viene con un ID oculto
    name = owner["name"] if src.IsFromMe else (contact or ev.Info.Pushname or src.Sender.User)
    _archive_add([(_jid_text(src.Chat), ev.Info.ID, _jid_text(src.Sender), name,
                   _seconds(ev.Info.Timestamp) or int(time.time()), int(src.IsFromMe), raw or text)])
    if src.IsFromMe and not raw.lstrip().startswith("."):
        return  # lo tuyo solo interesa si es una orden para el bot (".jarvis ...", ".stop")
    if src.IsGroup:
        group = _name_of_group(cl, src.Chat)
        who = f"{name} in {group}"
        _seen[_jid_text(src.Chat)] = (group, src.Chat)
    else:
        who = name if not src.IsFromMe else (_name_of_contact(cl, src.Chat) or src.Chat.User)
        if not src.IsFromMe:
            _seen[_jid_text(src.Chat)] = (who, src.Chat)
    if media == "sticker" and STICKERS["folder"]:
        threading.Thread(target=_save_sticker, args=(ev,), daemon=True).start()
    if (_seconds(ev.Info.Timestamp) or time.time()) < _started[0] - 20:
        return  # llego mientras TALOS estaba cerrado: queda guardado (lo puede leer), pero no se responde
    on_message({"who": who, "name": (ev.Info.Pushname or name).split()[0] if (ev.Info.Pushname or name) else "",
                "text": text, "raw": raw, "is_group": src.IsGroup, "chat": src.Chat,
                "sender": src.Sender, "from_me": src.IsFromMe,
                "is_audio": ev.Message.HasField("audioMessage"), "media": media, "event": ev,
                "quoted": quoted, "quoted_kind": quoted_kind, "quoted_text": quoted_text,
                "reply_to_bot": bool(quoted_id) and quoted_id in bot_ids, "quoted_id": quoted_id,
                "contact": contact or "", "pushname": ev.Info.Pushname or ""})


def _saved_name(cl, src):
    """Nombre con el que tienes guardado al remitente, probando su numero real si viene con ID oculto (LID)."""
    candidates = [src.Sender]
    if src.HasField("SenderAlt") and src.SenderAlt.User:
        candidates.append(src.SenderAlt)
    if src.Sender.Server == "lid":
        try:
            candidates.append(cl.get_pn_from_lid(src.Sender))
        except Exception:
            pass
    for jid in candidates:
        name = _name_of_contact(cl, jid)
        if name:
            return name
    return None


def _quoted(msg):
    """El mensaje al que respondieron (si respondieron a uno): (mensaje, tipo, texto).

    tipo: "image", "sticker", "video", "audio", "text" o None."""
    for field in ("extendedTextMessage", "imageMessage", "videoMessage", "stickerMessage", "audioMessage"):
        if msg.HasField(field):
            ctx = getattr(msg, field).contextInfo
            if ctx.HasField("quotedMessage"):
                q = ctx.quotedMessage
                kind = ("image" if q.HasField("imageMessage") else "sticker" if q.HasField("stickerMessage")
                        else "video" if q.HasField("videoMessage") else "audio" if q.HasField("audioMessage")
                        else "text")
                text = (q.conversation or q.extendedTextMessage.text or q.imageMessage.caption
                        or q.videoMessage.caption or "")
                return q, kind, text, ctx.stanzaID
    return None, None, "", ""


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


def title_of(chat_key):
    """Nombre del grupo o contacto de ese chat (si ya se vio)."""
    return (_seen.get(chat_key) or ("",))[0]


def import_export(path, chat_key, owner_names=()):
    """Guarda en el archivo los mensajes de un chat exportado (.txt de WhatsApp). Solo los mas viejos que lo
    que ya hay guardado, para no repetir. Devuelve cuantos guardo."""
    import datetime
    pat = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4}),? (\d{1,2}):(\d{2})(?:\s*([ap])\.?\s?m\.?)? - ([^:]+?): (.*)$", re.I)
    with open(path, encoding="utf-8") as f:
        text = f.read().replace("\u200e", "").replace("\u202f", " ")
    found, day_first = [], False
    for line in text.splitlines():
        hit = pat.match(line)
        if hit:
            found.append(list(hit.groups()))
            day_first = day_first or int(hit.group(1)) > 12
        elif found and not re.match(r"^\d{1,2}/\d{1,2}/\d{2,4},", line):
            found[-1][7] += "\n" + line
    first = _query("SELECT MIN(ts) FROM msgs WHERE chat=? AND id NOT LIKE 'exp-%'", (chat_key,))
    limit = (first[0][0] if first and first[0][0] else None)
    mine = {n.lower() for n in owner_names}
    rows = []
    for i, (a, b, y, hh, mm, ampm, who, body) in enumerate(found):
        if "<media omitted>" in body.lower() or "<multimedia omitido>" in body.lower():
            continue
        day, month = (int(a), int(b)) if day_first else (int(b), int(a))
        year = int(y) + (2000 if len(y) == 2 else 0)
        hour = int(hh) % 12 + (12 if ampm and ampm.lower() == "p" else 0) if ampm else int(hh)
        ts = int(time.mktime(datetime.datetime(year, month, day, hour, int(mm)).timetuple()))
        if limit and ts >= limit:
            continue  # eso ya lo trajo WhatsApp
        me = who.strip().lower() in mine
        body = body.replace("<This message was edited>", "").strip()
        rows.append((chat_key, f"exp-{i}", "", owner["name"] if me else who.strip(), ts, int(me), body))
    _archive_add(rows)
    return len(rows)


def key_of(jid):
    """Texto unico de un JID, para usarlo como clave."""
    return _jid_text(jid)


def jid_for_number(number):
    """JID de un número con código de país (solo dígitos)."""
    from neonize.utils import build_jid
    return build_jid(number)


def typing(jid, on=True):
    """Muestra (o quita) el "escribiendo..." en el chat."""
    from neonize.utils.enum import ChatPresence, ChatPresenceMedia
    try:
        state = ChatPresence.CHAT_PRESENCE_COMPOSING if on else ChatPresence.CHAT_PRESENCE_PAUSED
        _client.send_chat_presence(jid, state, ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT)
    except Exception:
        pass


def download_audio(ev):
    """Bytes del audio (nota de voz), foto, sticker o video de un mensaje que llego."""
    return _client.download_any(ev.Message)


download_media = download_audio


STICKERS = {"folder": None}   # carpeta donde se guardan los stickers que te mandan (el bot los reusa)


def _save_sticker(ev):
    try:
        import hashlib
        data = _client.download_any(ev.Message)
        if not data or data[:4] != b"RIFF" or len(data) > 900_000:
            return
        folder = STICKERS["folder"]
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, hashlib.sha1(data).hexdigest()[:16] + ".webp")
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(data)
            files = sorted((os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".webp")),
                           key=os.path.getmtime)
            for old in files[:-120]:  # maximo 120: se van los mas viejos
                os.remove(old)
    except Exception as e:
        print("Sticker:", e)


def send_sticker(jid, data, ev=None):
    """Manda un sticker (bytes .webp tal cual), respondiendo a ev si se puede."""
    try:
        response = _client.send_sticker(jid, data, quoted=ev, passthrough=True) if ev is not None else None
    except Exception:
        response = None
    if response is None:
        response = _client.send_sticker(jid, data, passthrough=True)
    _remember(response, jid, "(sticker)")


def download_quoted(m):
    """Bytes de la foto, sticker, video o audio del mensaje al que respondieron."""
    return _client.download_any(m["quoted"])


def _remember(response, chat=None, text=""):
    try:
        if response is not None and response.ID:
            bot_ids.add(response.ID)
            if len(bot_ids) > 5000:
                bot_ids.clear()
            if chat is not None:
                _archive_add([(_jid_text(chat), response.ID, "", "Talos (bot)", int(time.time()), 1, text)])
    except Exception:
        pass


def reply_text(ev, text, bot=False):
    """Responde citando el mensaje `ev`, para que en un grupo se vea a quien le contesta."""
    response = _client.reply_message(text, ev)
    if bot:
        _remember(response, ev.Info.MessageSource.Chat, text)


def send_text(jid, text, bot=False):
    response = _client.send_message(jid, text)
    if bot:
        _remember(response, jid, text)


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
