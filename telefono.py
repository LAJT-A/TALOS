"""Enlace Bluetooth entre el celular y Jarvis.

El celular se conecta al "puerto COM entrante" de Bluetooth de Windows y manda
una frase por linea. Jarvis la atiende como si la hubieras dicho al microfono y
le devuelve la respuesta, tambien una linea por frase.

Las lineas que empiezan por # quedan reservadas para la app (llamadas, musica).
"""
import queue
import threading
import time

inbox = queue.Queue()    # frases que llegan del celular
signals = queue.Queue()  # lineas "#..." que mande la app
link = {"serial": None, "port": None}
_lock = threading.Lock()


def find_ports():
    """Puertos COM de Bluetooth; primero los entrantes (los que esperan al celular)."""
    from serial.tools import list_ports
    found = []
    for p in list_ports.comports():
        info = f"{p.description} {p.hwid}".upper()
        if "BTHENUM" in info or "BLUETOOTH" in info:
            incoming = "_000000000000" in info or "&000000000000" in info
            found.append((0 if incoming else 1, p.device, p.description))
    return sorted(found)


def _loop(port):
    import serial
    warned = False
    while True:
        name = port
        if not name:
            ports = find_ports()
            incoming = [p for p in ports if p[0] == 0]
            if incoming:
                name = incoming[0][1]
            elif not warned:
                print("Celular: no hay puerto COM entrante de Bluetooth. Crea uno en "
                      "'Mas opciones de Bluetooth' > 'Puertos COM' > 'Agregar' > 'Entrante'.")
                if ports:
                    print("Celular: puertos Bluetooth que veo:", ", ".join(f"{p[1]} ({p[2]})" for p in ports))
                warned = True
        if not name:
            time.sleep(10)
            continue
        try:
            ser = serial.Serial(name, 115200, timeout=1, write_timeout=20)
        except Exception as e:
            if not warned:
                print(f"Celular: no pude abrir {name}: {e}")
                warned = True
            time.sleep(5)
            continue
        link.update(serial=ser, port=name)
        print(f"Celular: esperando en {name}")
        warned = False
        buffer = b""
        try:
            while True:
                data = ser.read(256)
                if not data:
                    continue
                buffer += data
                while b"\n" in buffer or b"\r" in buffer:
                    cut = min(i for i in (buffer.find(b"\n"), buffer.find(b"\r")) if i >= 0)
                    line, buffer = buffer[:cut], buffer[cut + 1:]
                    text = line.decode("utf-8", "ignore").strip()
                    if text.startswith("#"):
                        signals.put(text[1:].strip())
                    elif text:
                        inbox.put(text)
        except Exception as e:
            print("Celular: se corto la conexion:", e)
        finally:
            link["serial"] = None
            try:
                ser.close()
            except Exception:
                pass
        time.sleep(3)


def start(port=""):
    """Empieza a esperar al celular. port="" busca solo el puerto entrante."""
    try:
        import serial  # noqa: F401  (solo comprueba que esta instalado)
    except ImportError:
        print("Celular: falta instalar pyserial (pip install pyserial).")
        return False
    threading.Thread(target=_loop, args=(port,), daemon=True).start()
    return True


def send(text):
    """Manda una linea al celular. False si no hay conexion."""
    ser = link["serial"]
    if ser is None:
        return False
    try:
        with _lock:
            ser.write((text.replace("\n", " ") + "\r\n").encode("utf-8"))
        return True
    except Exception as e:
        print("Celular: no pude responderle:", e)
        return False
