"""Ventana del bot de WhatsApp de TALOS: los chats a la izquierda (como WhatsApp) y la conversacion
a la derecha, con botones para parar cada chat o todos.

La abre jarvis.py solo. Lee lo que pasa de bot_eventos.jsonl y le manda las ordenes a jarvis.py
escribiendo en bot_comandos.txt ("stop <chat>" o "stop_all").
"""
import json
import os
import sys
import tkinter as tk
from tkinter import font as tkfont

HERE = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
EVENTS = os.path.join(HERE, "bot_eventos.jsonl")
COMMANDS = os.path.join(HERE, "bot_comandos.txt")
ICON = os.path.join(HERE, "talos.ico")

BG = "#0b0e13"          # fondo del chat
SIDE = "#11151c"        # barra de chats
SIDE_HOVER = "#171c25"
SIDE_SEL = "#1c2330"
HEAD = "#141922"
LINE = "#1f2632"
TEXT = "#e9edf1"
MUTED = "#8a94a3"
FAINT = "#5c6573"
ACCENT = "#25d366"
RED = "#f0524f"
IN_BUBBLE = "#1d232d"
OUT_BUBBLE = "#0f5a43"
NOTE = "#3a3220"
AVATARS = ["#2f80ed", "#9b51e0", "#f2994a", "#eb5757", "#27ae60", "#56ccf2", "#bb6bd9", "#f2c94c"]


def send(command):
    with open(COMMANDS, "a", encoding="utf-8") as f:
        f.write(command + "\n")


def split_who(who):
    """"Diego in sayago x" -> ("Diego", "sayago x")."""
    person, _, group = (who or "").partition(" in ")
    if person.startswith("chat "):
        person = "Tú (órdenes)"
    return person.strip() or "Chat", group.strip()


def initials(name):
    parts = [p for p in name.replace("(", " ").split() if p[:1].isalnum()]
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper() if parts else "?"


class Chat:
    """Un chat: su fila en la izquierda y sus mensajes."""

    def __init__(self, app, key, who):
        self.app, self.key, self.who = app, key, who
        self.person, self.group = split_who(who) if key != "*" else ("Todos los chats", "")
        self.active = key != "*"
        self.events = []
        color = AVATARS[sum(map(ord, self.person)) % len(AVATARS)] if key != "*" else ACCENT

        self.row = tk.Frame(app.list, bg=SIDE, cursor="hand2", padx=12, pady=9)
        self.row.pack(fill="x")
        self.avatar = tk.Canvas(self.row, width=40, height=40, bg=SIDE, highlightthickness=0)
        self.avatar.create_oval(1, 1, 39, 39, fill=color, outline="")
        self.avatar.create_text(20, 20, text="✦" if key == "*" else initials(self.person), fill="white",
                                font=app.f_avatar)
        self.dot = self.avatar.create_oval(29, 29, 39, 39, fill=ACCENT if self.active else SIDE, outline=SIDE,
                                           width=2)
        self.avatar.pack(side="left")
        self.info = tk.Frame(self.row, bg=SIDE)
        self.info.pack(side="left", fill="x", expand=True, padx=(10, 0))
        self.title = tk.Label(self.info, text=self.person, bg=SIDE, fg=TEXT, font=app.f_bold, anchor="w")
        self.title.pack(fill="x")
        self.sub = tk.Label(self.info, text=self.group or ("todo lo que pasa" if key == "*" else "chat privado"),
                            bg=SIDE, fg=MUTED, font=app.f_small, anchor="w")
        self.sub.pack(fill="x")
        for w in (self.row, self.avatar, self.info, self.title, self.sub):
            w.bind("<Button-1>", lambda e: app.show(self))
            w.bind("<Enter>", lambda e: self.paint(hover=True))
            w.bind("<Leave>", lambda e: self.paint())

    def paint(self, hover=False):
        color = SIDE_SEL if self.app.current is self else (SIDE_HOVER if hover else SIDE)
        for w in (self.row, self.title, self.sub, self.avatar, self.info):
            w.configure(bg=color)
        self.avatar.itemconfigure(self.dot, fill=ACCENT if self.active else color, outline=color)

    def add(self, ev):
        self.events.append(ev)
        kind = ev.get("kind")
        if kind in ("in", "out"):
            who = "Talos: " if kind == "out" else (f"{split_who(ev.get('who'))[0]}: " if self.key == "*" else "")
            preview = (who + ev.get("text", "")).replace("\n", " ")
            self.sub.configure(text=preview[:40] + ("…" if len(preview) > 40 else ""))
        if self.app.current is self:
            self.app.draw(ev, self)

    def set_active(self, active):
        self.active = active
        self.paint()
        if self.app.current is self:
            self.app.header(self)


class App:
    def __init__(self):
        try:  # en Windows: que la barra de tareas muestre el logo de TALOS y no el de Python
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LAJT.Talos.Bot")
        except Exception:
            pass
        self.root = tk.Tk()
        self.root.title("TALOS · Bot de WhatsApp")
        self.root.geometry("1040x680")
        self.root.minsize(760, 480)
        self.root.configure(bg=BG)
        try:
            self.root.iconbitmap(ICON)
        except Exception:
            pass
        base = "Segoe UI" if "Segoe UI" in tkfont.families() else "DejaVu Sans"
        self.f_text = tkfont.Font(family=base, size=10)
        self.f_bold = tkfont.Font(family=base, size=10, weight="bold")
        self.f_small = tkfont.Font(family=base, size=8)
        self.f_title = tkfont.Font(family=base, size=12, weight="bold")
        self.f_brand = tkfont.Font(family=base, size=15, weight="bold")
        self.f_avatar = tkfont.Font(family=base, size=11, weight="bold")

        # --- izquierda: marca + lista de chats ---
        side = tk.Frame(self.root, bg=SIDE, width=290)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=SIDE, padx=16, pady=14)
        brand.pack(fill="x")
        self.logo = None
        try:
            from PIL import Image, ImageTk
            self.logo = ImageTk.PhotoImage(Image.open(ICON).convert("RGBA").resize((30, 30)))
            tk.Label(brand, image=self.logo, bg=SIDE).pack(side="left", padx=(0, 10))
        except Exception:
            pass
        tk.Label(brand, text="TALOS", bg=SIDE, fg=TEXT, font=self.f_brand).pack(side="left")
        self.count = tk.Label(brand, text="", bg=SIDE, fg=MUTED, font=self.f_small)
        self.count.pack(side="right")
        tk.Frame(side, bg=LINE, height=1).pack(fill="x")
        stop_all = tk.Label(side, text="■  Parar todos", bg=RED, fg="white", font=self.f_bold, pady=10,
                            cursor="hand2")
        stop_all.pack(fill="x", side="bottom", padx=14, pady=14)
        stop_all.bind("<Button-1>", lambda e: send("stop_all"))
        self.list = tk.Frame(side, bg=SIDE)
        self.list.pack(fill="both", expand=True)

        # --- derecha: cabecera + mensajes ---
        main = tk.Frame(self.root, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self.head = tk.Frame(main, bg=HEAD, height=62, padx=18)
        self.head.pack(fill="x")
        self.head.pack_propagate(False)
        self.h_name = tk.Label(self.head, text="", bg=HEAD, fg=TEXT, font=self.f_title)
        self.h_name.pack(side="left")
        self.h_status = tk.Label(self.head, text="", bg=HEAD, fg=MUTED, font=self.f_small)
        self.h_status.pack(side="left", padx=12, pady=(4, 0))
        self.h_close = tk.Label(self.head, text="✕  Quitar", bg=HEAD, fg=MUTED, font=self.f_text, cursor="hand2",
                                padx=10)
        self.h_stop = tk.Label(self.head, text="■  Parar", bg=RED, fg="white", font=self.f_bold, cursor="hand2",
                               padx=14, pady=6)
        self.h_stop.bind("<Button-1>", lambda e: self.stop_current())
        self.h_close.bind("<Button-1>", lambda e: self.remove_current())
        tk.Frame(main, bg=LINE, height=1).pack(fill="x")

        box = tk.Frame(main, bg=BG)
        box.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(box, bg=BG, highlightthickness=0)
        bar = tk.Scrollbar(box, command=self.canvas.yview, width=10, bg=BG, troughcolor=BG, bd=0,
                           activebackground=LINE)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.resize)
        self.root.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.root.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.root.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))

        self.chats = {}
        self.current = None
        self.width = 700
        self.all = Chat(self, "*", "")
        self.show(self.all)
        self.offset = 0
        self.root.after(200, self.poll)

    # ---------- dibujo ----------
    def resize(self, e):
        self.width = e.width
        self.canvas.itemconfigure(self.win, width=e.width)

    def header(self, chat):
        self.h_name.configure(text=chat.person + (f"  ·  {chat.group}" if chat.group else ""))
        self.h_stop.pack_forget()
        self.h_close.pack_forget()
        if chat.key == "*":
            self.h_status.configure(text="")
            return
        self.h_status.configure(text="● activo" if chat.active else "detenido", fg=ACCENT if chat.active else FAINT)
        self.h_close.pack(side="right")
        self.h_stop.pack(side="right", padx=8)
        self.h_stop.configure(bg=RED if chat.active else LINE, fg="white" if chat.active else FAINT)

    def show(self, chat):
        old, self.current = self.current, chat
        if old:
            old.paint()
        chat.paint()
        self.header(chat)
        for w in self.inner.winfo_children():
            w.destroy()
        tk.Frame(self.inner, bg=BG, height=10).pack()
        for ev in chat.events[-300:]:
            self.draw(ev, chat, scroll=False)
        self.root.after(30, lambda: self.canvas.yview_moveto(1.0))

    def draw(self, ev, chat, scroll=True):
        kind, text, when = ev.get("kind"), ev.get("text", ""), ev.get("time", "")
        wrap = max(260, int(self.width * 0.6))
        row = tk.Frame(self.inner, bg=BG)
        row.pack(fill="x", padx=18, pady=3)
        if kind in ("in", "out"):
            out = kind == "out"
            bg = OUT_BUBBLE if out else IN_BUBBLE
            bubble = tk.Frame(row, bg=bg, padx=12, pady=7)
            bubble.pack(side="right" if out else "left")
            if not out or chat.key == "*":
                name = ("Talos → " + split_who(ev.get("who"))[0]) if out else split_who(ev.get("who"))[0]
                tk.Label(bubble, text=name, bg=bg, fg="#7ee2a8" if out else ACCENT, font=self.f_bold,
                         anchor="w").pack(fill="x")
            tk.Label(bubble, text=text, bg=bg, fg=TEXT, font=self.f_text, wraplength=wrap, justify="left",
                     anchor="w").pack(fill="x")
            meta = when + (f"  ·  {ev['secs']}" if ev.get("secs") else "")
            tk.Label(bubble, text=meta, bg=bg, fg="#9fc9b5" if out else FAINT, font=self.f_small,
                     anchor="e").pack(fill="x")
        elif kind == "note":
            tk.Label(row, text=text, bg=NOTE, fg="#ffd56b", font=self.f_text, padx=12, pady=5,
                     wraplength=wrap).pack()
        else:
            icon = {"start": "▶  ", "stop": "■  "}.get(kind, "")
            tk.Label(row, text=f"{icon}{text}   {when}", bg=BG, fg=FAINT, font=self.f_small,
                     wraplength=wrap).pack()
        if scroll:
            self.root.after(30, lambda: self.canvas.yview_moveto(1.0))

    # ---------- botones ----------
    def stop_current(self):
        chat = self.current
        if chat and chat.key != "*" and chat.active:
            send(f"stop {chat.key}")
            self.h_status.configure(text="parando…", fg=MUTED)

    def remove_current(self):
        chat = self.current
        if not chat or chat.key == "*":
            return
        if chat.active:
            send(f"stop {chat.key}")
        chat.row.destroy()
        self.chats.pop(chat.key, None)
        self.show(self.all)
        self.counter()

    # ---------- eventos de TALOS ----------
    def chat(self, key, who):
        if key not in self.chats:
            self.chats[key] = Chat(self, key, who or key)
        return self.chats[key]

    def counter(self):
        active = sum(1 for c in self.chats.values() if c.active)
        self.count.configure(text=f"{active} activo" + ("" if active == 1 else "s"))

    def handle(self, ev):
        key, kind = ev.get("key"), ev.get("kind")
        if kind == "reset":
            for c in self.chats.values():
                c.set_active(False)
        elif kind == "stop":
            for k in ev.get("keys", []):
                if k in self.chats:
                    self.chats[k].set_active(False)
                    self.chats[k].add(ev)
            self.all.add(ev)
        elif key:
            chat = self.chat(key, ev.get("who"))
            if kind == "start" and not chat.active:
                chat.set_active(True)
            chat.row.pack_forget()
            chat.row.pack(fill="x", after=self.all.row)  # el mas reciente arriba
            chat.add(ev)
            if kind in ("in", "out", "note", "start"):
                self.all.add(ev)
        else:
            self.all.add(ev)
        self.counter()

    def poll(self):
        try:
            size = os.path.getsize(EVENTS)
            if size < self.offset:
                self.offset = 0
            if size > self.offset:
                with open(EVENTS, "rb") as f:
                    f.seek(self.offset)
                    data = f.read()
                end = data.rfind(b"\n") + 1
                self.offset += end
                for line in data[:end].decode("utf-8", "replace").splitlines():
                    try:
                        self.handle(json.loads(line))
                    except Exception as e:
                        print("evento:", e)
        except OSError:
            pass
        self.root.after(300, self.poll)


if __name__ == "__main__":
    App().root.mainloop()
