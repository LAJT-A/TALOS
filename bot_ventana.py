"""Ventana del bot de WhatsApp de TALOS: una pestaña por chat, con botones para pararlos.

La abre jarvis.py solo. Lee lo que pasa de bot_eventos.jsonl y le manda las ordenes a jarvis.py
escribiendo en bot_comandos.txt ("stop <chat>" o "stop_all").
"""
import json
import os
import sys
import tkinter as tk
from tkinter import ttk

HERE = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
EVENTS = os.path.join(HERE, "bot_eventos.jsonl")
COMMANDS = os.path.join(HERE, "bot_comandos.txt")

BG, PANEL, CARD = "#0f1115", "#171a21", "#1f232c"
TEXT, MUTED, ACCENT, RED = "#e8eaed", "#8b93a1", "#25d366", "#ef5350"
IN_BUBBLE, OUT_BUBBLE = "#262b35", "#0b5d43"
FONT = ("Segoe UI", 10)


def send(command):
    with open(COMMANDS, "a", encoding="utf-8") as f:
        f.write(command + "\n")


class ChatTab:
    def __init__(self, app, key, who):
        self.app, self.key, self.who, self.active = app, key, who, True
        self.frame = tk.Frame(app.tabs, bg=BG)
        head = tk.Frame(self.frame, bg=PANEL, padx=14, pady=10)
        head.pack(fill="x")
        self.dot = tk.Label(head, text="●", fg=ACCENT, bg=PANEL, font=("Segoe UI", 12))
        self.dot.pack(side="left")
        tk.Label(head, text=who.replace(" in ", "  ·  "), fg=TEXT, bg=PANEL, font=("Segoe UI Semibold", 12)).pack(side="left", padx=8)
        self.status = tk.Label(head, text="activo", fg=MUTED, bg=PANEL, font=FONT)
        self.status.pack(side="left")
        if key != "*":
            self.close = tk.Button(head, text="✕ Cerrar", command=self.remove, bg=CARD, fg=MUTED, bd=0,
                                   activebackground=CARD, activeforeground=TEXT, padx=10, pady=4, font=FONT,
                                   cursor="hand2")
            self.close.pack(side="right", padx=(8, 0))
            self.stop = tk.Button(head, text="■ Parar", command=self.ask_stop, bg=RED, fg="white", bd=0,
                                  activebackground="#c62828", activeforeground="white", padx=12, pady=4,
                                  font=("Segoe UI Semibold", 10), cursor="hand2")
            self.stop.pack(side="right")
        body = tk.Frame(self.frame, bg=BG)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, bg=BG, fg=TEXT, bd=0, wrap="word", font=FONT, padx=14, pady=10,
                            state="disabled", cursor="arrow", highlightthickness=0)
        bar = ttk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        t = self.text
        t.tag_configure("in", background=IN_BUBBLE, lmargin1=10, lmargin2=10, rmargin=220, spacing1=10,
                        spacing3=2)
        t.tag_configure("out", background=OUT_BUBBLE, lmargin1=220, lmargin2=220, rmargin=10, spacing1=10,
                        spacing3=2)
        t.tag_configure("who", foreground=ACCENT, font=("Segoe UI Semibold", 9))
        t.tag_configure("meta", foreground=MUTED, font=("Segoe UI", 8))
        t.tag_configure("info", foreground=MUTED, font=("Segoe UI", 9, "italic"), justify="center",
                        spacing1=6, spacing3=6)
        t.tag_configure("note", foreground="#ffd54f", font=("Segoe UI", 9), justify="center", spacing1=6,
                        spacing3=6)
        app.tabs.add(self.frame, text=self.label())

    def label(self):
        name = self.who.replace(" in ", " · ")
        short = name if len(name) <= 28 else name[:26] + "…"
        return ("● " if self.active and self.key != "*" else "") + short

    def add(self, ev):
        kind, line, when = ev.get("kind"), ev.get("text", ""), ev.get("time", "")
        t = self.text
        t.configure(state="normal")
        if kind == "in":
            name = ev.get("name") or ""
            if self.key == "*" and ev.get("who"):
                name = ev["who"]
            if name:
                t.insert("end", f"  {name}\n", ("in", "who"))
            t.insert("end", f"  {line}  \n", "in")
            t.insert("end", f"  {when}\n", ("in", "meta"))
        elif kind == "out":
            if self.key == "*" and ev.get("who"):
                t.insert("end", f"  Talos → {ev['who']}\n", ("out", "who"))
            t.insert("end", f"  {line}  \n", "out")
            t.insert("end", f"  {when}" + (f" · {ev['secs']}" if ev.get("secs") else "") + "\n", ("out", "meta"))
        elif kind == "note":
            t.insert("end", f"{line}\n", "note")
        else:
            t.insert("end", f"{when}  {line}\n", "info")
        t.configure(state="disabled")
        t.see("end")

    def set_active(self, active):
        self.active = active
        self.dot.configure(fg=ACCENT if active else MUTED)
        self.status.configure(text="activo" if active else "detenido")
        if self.key != "*":
            self.stop.configure(state="normal" if active else "disabled",
                                bg=RED if active else CARD)
        self.app.tabs.tab(self.frame, text=self.label())

    def ask_stop(self):
        send(f"stop {self.key}")
        self.status.configure(text="parando…")

    def remove(self):
        if self.active:
            self.ask_stop()
        self.app.tabs.forget(self.frame)
        self.app.chats.pop(self.key, None)


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("TALOS · Bot de WhatsApp")
        self.root.geometry("820x620")
        self.root.configure(bg=BG)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(8, 6, 8, 0))
        style.configure("TNotebook.Tab", background=CARD, foreground=MUTED, padding=(14, 6), borderwidth=0,
                        font=FONT)
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", TEXT)])
        style.configure("Vertical.TScrollbar", background=CARD, troughcolor=BG, borderwidth=0, arrowsize=0)

        top = tk.Frame(self.root, bg=BG, padx=14, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="TALOS", fg=ACCENT, bg=BG, font=("Segoe UI Black", 14)).pack(side="left")
        tk.Label(top, text="  bot de WhatsApp", fg=MUTED, bg=BG, font=("Segoe UI", 11)).pack(side="left")
        tk.Button(top, text="■ Parar todo", command=lambda: send("stop_all"), bg=RED, fg="white", bd=0,
                  activebackground="#c62828", activeforeground="white", padx=14, pady=5,
                  font=("Segoe UI Semibold", 10), cursor="hand2").pack(side="right")
        self.count = tk.Label(top, text="0 activos", fg=MUTED, bg=BG, font=FONT)
        self.count.pack(side="right", padx=12)

        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True)
        self.chats = {}
        self.all = ChatTab(self, "*", "Todos")
        self.offset = 0
        self.root.after(200, self.poll)

    def chat(self, key, who):
        if key not in self.chats:
            self.chats[key] = ChatTab(self, key, who or key)
        return self.chats[key]

    def handle(self, ev):
        key, kind = ev.get("key"), ev.get("kind")
        if kind == "reset":  # TALOS arranco de nuevo
            for tab in list(self.chats.values()):
                tab.set_active(False)
        elif kind == "stop":
            for k in ev.get("keys", []):
                if k in self.chats:
                    self.chats[k].set_active(False)
                    self.chats[k].add(ev)
            self.all.add(ev)
        elif key:
            tab = self.chat(key, ev.get("who"))
            if kind == "start":
                if not tab.active:
                    tab.set_active(True)
                self.tabs.select(tab.frame)
            tab.add(ev)
            if kind in ("in", "out", "note", "start"):
                self.all.add(ev)
        else:
            self.all.add(ev)
        active = sum(1 for t in self.chats.values() if t.active)
        self.count.configure(text=f"{active} activo" + ("" if active == 1 else "s"))

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
                    except Exception:
                        pass
        except OSError:
            pass
        self.root.after(300, self.poll)


if __name__ == "__main__":
    App().root.mainloop()
