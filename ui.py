"""Interfaz de Jarvis: un anillo de luz fluido, entre halo y orbe.

Los colores estan en PALETTES y el tamano en ORB_SIZE. En Windows usa transparencia
real por pixel; si no esta disponible, recurre a un color transparente.
"""
import math, os, sys, time
import tkinter as tk
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

ORB_SIZE = 210       # zona del anillo, con su brillo, en pixeles (a 100 % de escala)
PANEL_W = 250        # ancho del panel de texto
MARGIN = (20, 70)    # distancia a la derecha y al borde inferior de la pantalla
FPS_ACTIVE = 30
FPS_SLEEP = 12       # en espera consume menos, por ejemplo mientras juegas
KEY = (255, 0, 254)  # solo se usa si falla la transparencia real

# color 1, color 2, color 3, brillo, movimiento, velocidad de giro
PALETTES = {
    "sleep":     ((74, 104, 214), (112, 76, 214), (70, 150, 214), 0.62, 0.16, 0.22),
    "awake":     ((80, 190, 255), (120, 110, 255), (90, 240, 230), 1.0, 0.55, 0.7),
    "listening": ((60, 245, 175), (40, 175, 255), (160, 255, 215), 1.0, 0.85, 0.7),
    "thinking":  ((255, 175, 60), (255, 90, 115), (255, 225, 125), 1.0, 0.55, 2.4),
    "speaking":  ((85, 150, 255), (175, 85, 255), (255, 90, 190), 1.0, 1.25, 0.9),
}
LABELS = {"sleep": "EN ESPERA", "awake": "ACTIVO", "listening": "ESCUCHANDO",
          "thinking": "PROCESANDO", "speaking": "RESPONDIENDO"}
TEXT_ES = {"Listening...": "Te escucho...", "Say yes to confirm": "Di sí para confirmar",
           "Looking at your screen...": "Mirando tu pantalla..."}


def _font(names, size):
    for name in names:
        for path in (os.path.join(r"C:\Windows\Fonts", name), name):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default(size)


def _wrap(draw, text, font, width, max_lines):
    lines, cur = [], ""
    for word in text.split():
        probe = (cur + " " + word).strip()
        if draw.textlength(probe, font=font) <= width:
            cur = probe
            continue
        if cur:
            lines.append(cur)
        cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and draw.textlength(lines[-1] + "...", font=font) > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] = lines[-1].rstrip() + "..."
    return lines


class Renderer:
    """Dibuja cada cuadro con numpy; no depende de Tkinter."""

    def __init__(self, scale=1.0):
        self.scale = scale
        self.d = int(ORB_SIZE * scale)
        self.panel_w = int(PANEL_W * scale)
        self.gap = int(2 * scale)
        self.w = self.panel_w + self.gap + self.d
        self.h = self.d
        y, x = np.mgrid[0:self.d, 0:self.d].astype(np.float32)
        c = (self.d - 1) / 2
        x = (x - c) / c
        y = (y - c) / c
        self.x, self.y = x, y
        self.rad = np.hypot(x, y)
        self.ang = ((np.arctan2(y, x) % math.tau) / math.tau * 720).astype(np.int32) % 720
        self.theta = np.arange(720, dtype=np.float32) / 720 * math.tau
        self.params = self._target("sleep")
        self.f_head = _font(["bahnschrift.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"], int(11 * scale))
        self.f_text = _font(["segoeui.ttf", "DejaVuSans.ttf"], int(14 * scale))
        self.panel_cache = (None, None)
        self.last_t = 0.0
        self.phase = 0.0

    def _target(self, state):
        c1, c2, c3, bright, amp, spin = PALETTES.get(state, PALETTES["awake"])
        return np.array(c1 + c2 + c3 + (bright, amp, spin), dtype=np.float32)

    def orb(self, state, t):
        """Devuelve el anillo como RGB y alfa, en flotantes."""
        dt = min(0.2, max(0.0, t - self.last_t))
        self.last_t = t
        self.params += (self._target(state) - self.params) * min(1.0, dt * 6)
        p = self.params
        cols = p[:9].reshape(3, 3)
        bright, amp, spin = float(p[9]), float(p[10]), float(p[11])
        self.phase += dt * spin
        ph = self.phase
        th = self.theta

        # forma: el contorno ondula como un liquido
        wave = (0.060 * np.sin(3 * th + ph * 1.3 + 0.7 * math.sin(t * 0.7))
                + 0.040 * np.sin(5 * th - ph * 1.9)
                + 0.022 * np.sin(8 * th + ph * 2.7))
        if state in ("listening", "speaking"):  # pulso decorativo, no mide el microfono
            wave = wave * (0.8 + 0.35 * abs(math.sin(t * 4.7)) * abs(math.sin(t * 2.3 + 1)))
        breath = 0.012 * math.sin(t * 1.3)
        r_lut = 0.62 * (1 + breath + amp * wave)
        dist = self.rad - r_lut[self.ang]

        # color: tres tonos que giran alrededor del anillo
        a = th - ph * 0.9
        w1 = 0.5 + 0.5 * np.cos(a)
        w2 = 0.5 + 0.5 * np.cos(a - 2.1)
        w3 = 0.5 + 0.5 * np.cos(a + 2.1)
        total = w1 + w2 + w3
        lut = (cols[0][None] * (w1 / total)[:, None] + cols[1][None] * (w2 / total)[:, None]
               + cols[2][None] * (w3 / total)[:, None]) * 1.25
        rgb = np.clip(lut, 0, 255)[self.ang]
        # hacia el centro los tonos se mezclan, para que no se note el giro
        mix = np.exp(-(self.rad / 0.42) ** 2)[..., None]
        rgb = rgb + (lut.mean(axis=0) - rgb) * mix

        d = dist
        ring = np.exp(-(d / 0.042) ** 2)              # borde luminoso
        outer = np.exp(-np.maximum(d, 0) / 0.085) * (d > 0)   # brillo hacia afuera
        inner = np.exp(np.minimum(d, 0) / 0.30) * (d <= 0)    # cuerpo de vidrio con color
        shine = np.exp(-(((self.x + 0.20) ** 2 + (self.y + 0.24) ** 2) / 0.045))  # reflejo
        alpha = np.clip(ring + 0.45 * outer + 0.58 * inner + 0.28 * shine * (d <= 0), 0, 1) * bright
        # desvanece el brillo antes del borde de la ventana
        alpha *= np.clip((1.0 - self.rad) / 0.14, 0, 1)
        hot = np.clip(ring ** 4 * 0.30 + shine * (d <= 0) * 0.55, 0, 1)[..., None]
        rgb = rgb + (255 - rgb) * hot
        return rgb, alpha

    def panel(self, state, text, reveal=1.0):
        """Panel de texto como imagen RGBA, con esquinas suaves."""
        key = (state, text)
        if self.panel_cache[0] != key:
            col = tuple(int(v) for v in PALETTES.get(state, PALETTES["awake"])[0])
            s = self.scale
            w = self.panel_w
            probe = ImageDraw.Draw(Image.new("L", (1, 1)))
            lines = _wrap(probe, TEXT_ES.get(text, text), self.f_text, w - int(34 * s), 5)
            line_h = int(19 * s)
            h = int(46 * s) + line_h * max(1, len(lines))
            k = 3
            big = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
            d = ImageDraw.Draw(big)
            d.rounded_rectangle((0, 0, w * k - 1, h * k - 1), int(15 * s) * k, fill=(9, 12, 20, 226),
                                outline=col + (130,), width=k)
            img = big.resize((w, h), Image.LANCZOS)
            d = ImageDraw.Draw(img)
            x, y = int(17 * s), int(13 * s)
            dot = int(3 * s)
            d.ellipse((x, y + 2 * s, x + 2 * dot, y + 2 * s + 2 * dot), fill=col + (255,))
            d.text((x + 2 * dot + int(7 * s), y), LABELS.get(state, ""), font=self.f_head, fill=col + (255,))
            y = int(34 * s)
            for line in lines:
                d.text((x, y), line, font=self.f_text, fill=(232, 240, 246, 255))
                y += line_h
            self.panel_cache = (key, np.asarray(img, dtype=np.float32))
        arr = self.panel_cache[1]
        if reveal < 1:
            arr = arr.copy()
            arr[..., 3] *= reveal
        return arr

    def frame(self, state, t, text="", reveal=1.0):
        """Cuadro completo con alfa premultiplicado (RGBA, flotante 0-255)."""
        out = np.zeros((self.h, self.w, 4), dtype=np.float32)
        rgb, alpha = self.orb(state, t)
        ox = self.panel_w + self.gap
        out[:, ox:, :3] = rgb * alpha[..., None]
        out[:, ox:, 3] = alpha * 255
        if text:
            p = self.panel(state, text, reveal)
            ph, pw = p.shape[:2]
            py = (self.h - ph) // 2
            a = p[..., 3:] / 255
            out[py:py + ph, :pw, :3] = p[..., :3] * a
            out[py:py + ph, :pw, 3] = p[..., 3]
        return out


class LayeredWindow:
    """Transparencia real por pixel en Windows."""

    def __init__(self, root, w, h):
        import ctypes
        from ctypes import wintypes as wt
        self.ct = ctypes
        self.w, self.h = w, h
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        self.u, self.g = u, g
        u.GetAncestor.argtypes = [wt.HWND, wt.UINT]
        u.GetAncestor.restype = wt.HWND
        u.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
        u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.GetDC.argtypes = [wt.HWND]
        u.GetDC.restype = wt.HDC
        g.CreateCompatibleDC.argtypes = [wt.HDC]
        g.CreateCompatibleDC.restype = wt.HDC
        g.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
        g.SelectObject.restype = wt.HGDIOBJ

        class BLEND(ctypes.Structure):
            _fields_ = [("Op", ctypes.c_ubyte), ("Flags", ctypes.c_ubyte),
                        ("Alpha", ctypes.c_ubyte), ("Format", ctypes.c_ubyte)]

        class BIH(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

        u.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.c_void_p, ctypes.POINTER(wt.SIZE), wt.HDC,
                                          ctypes.POINTER(wt.POINT), wt.COLORREF, ctypes.POINTER(BLEND), wt.DWORD]
        u.UpdateLayeredWindow.restype = wt.BOOL
        g.CreateDIBSection.argtypes = [wt.HDC, ctypes.POINTER(BIH), wt.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
        g.CreateDIBSection.restype = wt.HBITMAP

        root.update_idletasks()
        self.hwnd = u.GetAncestor(root.winfo_id(), 2)
        style = u.GetWindowLongPtrW(self.hwnd, -20)
        u.SetWindowLongPtrW(self.hwnd, -20, style | 0x00080000 | 0x00000080)  # LAYERED | TOOLWINDOW
        self.screen = u.GetDC(None)
        self.dc = g.CreateCompatibleDC(self.screen)
        bih = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        self.bits = ctypes.c_void_p()
        bmp = g.CreateDIBSection(self.dc, ctypes.byref(bih), 0, ctypes.byref(self.bits), None, 0)
        if not bmp or not self.bits:
            raise OSError("CreateDIBSection fallo")
        g.SelectObject(self.dc, bmp)
        self.size = wt.SIZE(w, h)
        self.src = wt.POINT(0, 0)
        self.blend = BLEND(0, 0, 255, 1)

    def show(self, frame):
        bgra = np.clip(frame, 0, 255).astype(np.uint8)[..., [2, 1, 0, 3]]
        self.ct.memmove(self.bits, bgra.tobytes(), bgra.size)
        ok = self.u.UpdateLayeredWindow(self.hwnd, self.screen, None, self.ct.byref(self.size), self.dc,
                                        self.ct.byref(self.src), 0, self.ct.byref(self.blend), 2)
        if not ok:
            raise OSError("UpdateLayeredWindow fallo")


class KeyedWindow:
    """Alternativa sin transparencia por pixel: funde con un fondo oscuro."""

    def __init__(self, root, canvas, w, h, rnd):
        # El interior del anillo nunca se vuelve transparente, para no dejar huecos.
        self.solid = np.zeros((h, w), dtype=bool)
        self.solid[:, rnd.panel_w + rnd.gap:] = rnd.rad < 0.60
        self.photo = ImageTk.PhotoImage(Image.new("RGB", (w, h), KEY))
        canvas.create_image(0, 0, image=self.photo, anchor="nw")

    def show(self, frame):
        a = frame[..., 3:] / 255
        rgb = np.clip(frame[..., :3] + np.array((6, 9, 15), np.float32) * (1 - a), 0, 255)
        rgb[(frame[..., 3] < 28) & ~self.solid] = KEY
        self.photo.paste(Image.fromarray(rgb.astype(np.uint8), "RGB"))


def create(S, events):
    """Crea la ventana. S y events son los de jarvis.py."""
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    key_hex = "#%02x%02x%02x" % KEY
    root.config(bg=key_hex)
    scale = max(1.0, min(2.0, root.winfo_fpixels("1i") / 96))
    rnd = Renderer(scale)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{rnd.w}x{rnd.h}+{sw - rnd.w - MARGIN[0]}+{sh - rnd.h - MARGIN[1]}")
    cv = tk.Canvas(root, width=rnd.w, height=rnd.h, bg=key_hex, highlightthickness=0, bd=0)
    cv.pack()
    root.update()

    win = None
    if sys.platform == "win32":
        try:
            win = LayeredWindow(root, rnd.w, rnd.h)
            win.show(rnd.frame("sleep", 0.0))
        except Exception as e:
            print("Transparencia real no disponible:", e)
            win = None
    if win is None:
        try:
            root.attributes("-transparentcolor", key_hex)
        except tk.TclError:
            pass
        win = KeyedWindow(root, cv, rnd.w, rnd.h, rnd)

    ui = {"key": None, "opened": 0.0, "frame": 0}
    t0 = time.time()

    def tick():
        nonlocal win
        started = time.time()
        t = started - t0
        st = S["state"]
        txt = S["text"] if st != "sleep" else ""
        if txt and ui["key"] is None:
            ui["opened"] = t
        ui["key"] = txt or None
        reveal = min(1.0, (t - ui["opened"]) / 0.16) if txt else 1.0
        frame = rnd.frame(st, t, txt, reveal)
        try:
            win.show(frame)
        except Exception as e:
            print("Error de pantalla:", e)
            try:
                root.attributes("-transparentcolor", key_hex)
            except tk.TclError:
                pass
            win = KeyedWindow(root, cv, rnd.w, rnd.h, rnd)
        ui["frame"] += 1
        if ui["frame"] % 40 == 0:
            root.attributes("-topmost", True)
            root.lift()
        fps = FPS_SLEEP if st == "sleep" else FPS_ACTIVE
        root.after(max(1, int(1000 / fps - (time.time() - started) * 1000)), tick)

    drag = {"moved": False}

    def on_press(e):
        drag["x"], drag["y"] = e.x_root - root.winfo_x(), e.y_root - root.winfo_y()
        drag["sx"], drag["sy"] = e.x_root, e.y_root
        drag["moved"] = False
        drag["on_orb"] = e.x >= rnd.panel_w

    def on_motion(e):
        if abs(e.x_root - drag["sx"]) > 4 or abs(e.y_root - drag["sy"]) > 4:
            drag["moved"] = True
        if drag["moved"]:
            root.geometry(f"+{e.x_root - drag['x']}+{e.y_root - drag['y']}")

    def on_release(_):
        # Un clic sin arrastrar, sobre el anillo, activa a Jarvis.
        if not drag["moved"] and drag.get("on_orb") and S["state"] == "sleep":
            S["state"] = "awake"
            S["text"] = ""
            events.put("click")
        elif not drag["moved"] and drag.get("on_orb") and S["state"] == "speaking":
            S["stop"] = True  # un clic mientras habla lo hace callar

    menu = tk.Menu(root, tearoff=0, bg="#090c14", fg="#e8f0f6", bd=0,
                   activebackground="#1b2a44", activeforeground="#ffffff")
    menu.add_command(label="Cerrar Jarvis", command=lambda: os._exit(0))
    cv.bind("<ButtonPress-1>", on_press)
    cv.bind("<B1-Motion>", on_motion)
    cv.bind("<ButtonRelease-1>", on_release)
    cv.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
    root._jarvis_refs = (rnd,)
    root.after(10, tick)
    return root
