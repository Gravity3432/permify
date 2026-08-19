"""Permify GUI — a windowed Spotify player.

Built with tkinter (stdlib, no extra deps). Talks to the same engine API as
the terminal clients, so playback is battle-tested. Distinct visual identity.
"""
from __future__ import annotations

import threading
from typing import Optional

from .models import Snapshot

try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except Exception:  # pragma: no cover
    _HAS_PIL = False

# Permify palette
BG = "#0f1115"
SIDE = "#171a21"
PANEL = "#1f232c"
TEXT = "#e8e8ea"
MUTED = "#8a90a0"
ACCENT = "#7c5cff"     # periwinkle/violet — Permify's identity
ACCENT_DIM = "#5b43c0"
ACCENT_TEXT = "#ffffff"


class PermifyGUI:
    def __init__(self, engine, cfg: dict, demo: bool = False):
        self.engine = engine
        self.cfg = cfg
        self.demo = demo
        self.volume = int(cfg.get("volume", 60))
        self._stop = threading.Event()
        self._last_art = None
        self._photo = None
        self._playlists: list = []
        self._playlist_map: dict = {}

        import tkinter as tk
        self.tk = tk
        self.root = tk.Tk()
        self.root.title("Permify" + ("  ·  demo" if demo else ""))
        self.root.geometry("880x600")
        self.root.configure(bg=BG)
        self.root.minsize(640, 460)

        self._build_widgets()
        self._bind_keys()

        self.engine.start(self._toast)
        self.snap: Snapshot = self.engine.snapshot()

        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------ widgets
    def _build_widgets(self) -> None:
        import tkinter as tk

        # left sidebar: playlists + library
        side = tk.Frame(self.root, bg=SIDE, width=210)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="YOUR LIBRARY", bg=SIDE, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14, pady=(14, 6))
        self.lib = tk.Listbox(side, bg=SIDE, fg=TEXT, selectbackground=ACCENT,
                              selectforeground="#000", highlightthickness=0, bd=0,
                              font=("Segoe UI", 10))
        self.lib.pack(fill="both", expand=True, padx=8)
        self.lib.bind("<Double-Button-1>", lambda e: self._lib_open())
        tk.Button(side, text="↻ refresh", bg=SIDE, fg=TEXT, bd=0,
                  activebackground=ACCENT, command=self._refresh_library,
                  font=("Segoe UI", 9)).pack(fill="x", padx=10, pady=(8, 12))

        # main column
        main = tk.Frame(self.root, bg=BG)
        main.pack(side="right", fill="both", expand=True)

        # now playing header
        head = tk.Frame(main, bg=BG)
        head.pack(fill="x", padx=24, pady=(22, 10))
        self.art = tk.Label(head, bg=BG, text="♪", fg=ACCENT,
                            font=("Segoe UI", 44), width=6, height=3)
        self.art.pack(side="left")
        info = tk.Frame(head, bg=BG)
        info.pack(side="left", padx=18, fill="x", expand=True)
        self.title = tk.Label(info, text="Nothing playing", bg=BG, fg=TEXT,
                              font=("Segoe UI", 20, "bold"), anchor="w")
        self.title.pack(anchor="w")
        self.artist = tk.Label(info, text="", bg=BG, fg=MUTED,
                               font=("Segoe UI", 13), anchor="w")
        self.artist.pack(anchor="w")
        self.album = tk.Label(info, text="", bg=BG, fg=MUTED,
                              font=("Segoe UI", 10), anchor="w")
        self.album.pack(anchor="w")

        # progress
        pbar = tk.Frame(main, bg=BG)
        pbar.pack(fill="x", padx=24)
        self.progress = tk.Canvas(pbar, height=8, bg=PANEL, highlightthickness=0,
                                  bd=0)
        self.progress.pack(fill="x")
        self.progress.bind("<Button-1>", self._click_seek)
        self.progress.bind("<B1-Motion>", self._click_seek)
        self.time = tk.Label(main, text="0:00 / 0:00", bg=BG, fg=MUTED,
                             font=("Segoe UI", 9))
        self.time.pack(anchor="w", padx=24)

        # controls
        ctl = tk.Frame(main, bg=BG)
        ctl.pack(fill="x", padx=24, pady=(12, 8))
        tk.Button(ctl, text="⏮", bg=BG, fg=TEXT, bd=0, width=4,
                  font=("Segoe UI", 15), command=self._prev,
                  activebackground=BG).pack(side="left", padx=4)
        self.play_btn = tk.Button(ctl, text="▶", bg=ACCENT, fg=ACCENT_TEXT, bd=0,
                                  width=6, font=("Segoe UI", 15, "bold"),
                                  activebackground=ACCENT_DIM, command=self._toggle)
        self.play_btn.pack(side="left", padx=4)
        tk.Button(ctl, text="⏭", bg=BG, fg=TEXT, bd=0, width=4,
                  font=("Segoe UI", 15), command=self._next,
                  activebackground=BG).pack(side="left", padx=4)
        self.state = tk.Label(ctl, text="● idle", bg=BG, fg=MUTED,
                              font=("Segoe UI", 10))
        self.state.pack(side="left", padx=14)

        # bottom: volume, shuffle, repeat, search
        bot = tk.Frame(main, bg=BG)
        bot.pack(fill="x", padx=24, pady=(2, 8))
        tk.Label(bot, text="🔊", bg=BG, fg=MUTED).pack(side="left")
        self.vol = tk.Scale(bot, from_=0, to=100, orient="horizontal", bg=BG,
                            fg=TEXT, highlightthickness=0, bd=0, troughcolor=PANEL,
                            activebackground=ACCENT, command=self._set_volume)
        self.vol.set(self.volume)
        self.vol.pack(side="left", fill="x", expand=True, padx=8)
        self.shuf_btn = tk.Button(bot, text="⇄", bg=BG, fg=MUTED, bd=0, width=3,
                                  font=("Segoe UI", 12), command=self._shuffle)
        self.shuf_btn.pack(side="right", padx=2)
        self.rep_btn = tk.Button(bot, text="↻", bg=BG, fg=MUTED, bd=0, width=3,
                                 font=("Segoe UI", 12), command=self._repeat)
        self.rep_btn.pack(side="right", padx=2)

        # search
        srow = tk.Frame(main, bg=BG)
        srow.pack(fill="x", padx=24, pady=(4, 4))
        self.search_entry = tk.Entry(srow, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                                     bd=0, font=("Segoe UI", 11),
                                     highlightthickness=1, highlightbackground=PANEL,
                                     highlightcolor=ACCENT)
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.search_entry.insert(0, "  Search…")
        self.search_entry.bind("<Return>", lambda e: self._search())
        tk.Button(srow, text="Search", bg=ACCENT, fg=ACCENT_TEXT, bd=0,
                  font=("Segoe UI", 10, "bold"), command=self._search,
                  activebackground=ACCENT_DIM).pack(side="left", padx=(6, 0))

        # results / queue list
        tk.Label(main, text="UP NEXT", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=24)
        self.list_box = tk.Listbox(main, bg=BG, fg=TEXT, highlightthickness=0,
                                   bd=0, font=("Segoe UI", 11))
        self.list_box.pack(fill="both", expand=True, padx=24, pady=(2, 14))
        self.list_box.bind("<Double-Button-1>", lambda e: self._list_open())
        self._list_mode = "queue"

        self._toast_lbl = tk.Label(main, text="", bg=BG, fg=ACCENT,
                                   font=("Segoe UI", 9))
        self._toast_lbl.pack(side="bottom", pady=4)

    def _bind_keys(self):
        self.root.bind("<space>", lambda e: self._toggle())
        self.root.bind("<Left>", lambda e: self._seek(-5))
        self.root.bind("<Right>", lambda e: self._seek(5))

    # --------------------------------------------------------- library
    def _refresh_library(self):
        def work():
            try:
                pls = self.engine.get_playlists()
            except Exception:
                pls = []
            def fill():
                self._playlists = pls
                self._playlist_map = {}
                self.lib.delete(0, "end")
                self.lib.insert("end", "♥  Liked Songs")
                self._playlist_map[0] = "liked"
                for i, p in enumerate(pls, start=1):
                    self.lib.insert("end", f"  {p.name}")
                    self._playlist_map[i] = p
            self.root.after(0, fill)
        threading.Thread(target=work, daemon=True).start()

    def _lib_open(self):
        sel = self.lib.curselection()
        if not sel:
            return
        item = self._playlist_map.get(sel[0])
        if item == "liked":
            self._load_tracks(self.engine.get_liked, "Liked Songs")
        elif item:
            self._load_tracks(lambda: self.engine.get_playlist_tracks(item),
                              item.name)

    def _load_tracks(self, fetch, name):
        def work():
            try:
                tracks = fetch()
            except Exception:
                tracks = []
            def fill():
                self._search_results = tracks
                self._list_mode = "tracks"
                self.list_box.delete(0, "end")
                for t in tracks:
                    self.list_box.insert("end", f"{t.name}  —  {t.artists}")
            self.root.after(0, fill)
        threading.Thread(target=work, daemon=True).start()

    def _search(self):
        q = self.search_entry.get().replace("  Search…", "").strip()
        if not q:
            return
        self._load_tracks(lambda: self.engine.search(q), f"results: {q}")

    # --------------------------------------------------------- transport
    def _toggle(self):
        threading.Thread(target=self.engine.toggle, daemon=True).start()

    def _next(self):
        threading.Thread(target=self.engine.next, daemon=True).start()

    def _prev(self):
        threading.Thread(target=self.engine.prev, daemon=True).start()

    def _seek(self, delta_sec):
        self._seek_ms(int(self.snap.position_ms) + delta_sec * 1000)

    def _seek_ms(self, ms):
        threading.Thread(target=self.engine.seek_ms, args=(int(ms),),
                         daemon=True).start()

    def _click_seek(self, e):
        try:
            w = max(1, e.widget.winfo_width())
            r = max(0.0, min(1.0, e.x / w))
            self._seek_ms(int(self.snap.duration_ms * r))
        except Exception:
            pass

    def _set_volume(self, v):
        threading.Thread(target=self.engine.set_volume, args=(int(v),),
                         daemon=True).start()

    def _shuffle(self):
        threading.Thread(target=self.engine.shuffle_toggle, daemon=True).start()

    def _repeat(self):
        threading.Thread(target=self.engine.repeat_cycle, daemon=True).start()

    def _list_open(self):
        if self._list_mode == "tracks":
            sel = self.list_box.curselection()
            if sel and hasattr(self, "_search_results") and sel[0] < len(self._search_results):
                tracks = self._search_results
                self.engine.play_tracks(tracks, sel[0], "Permify")

    # ------------------------------------------------------------ poll
    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                self.snap = self.engine.snapshot()
                self._update()
            except Exception:
                pass
            self._stop.wait(0.5)

    def _update(self):
        snap = self.snap
        try:
            if snap.track:
                t = snap.track
                self.title.config(text=t.name)
                self.artist.config(text=t.artists)
                self.album.config(text=t.album)
                pos, dur = int(snap.position_ms or 0), int(snap.duration_ms or 0)
                self.time.config(text=f"{_fmt(pos)} / {_fmt(dur)}")
                self.progress.delete("all")
                w = max(1, self.progress.winfo_width())
                pct = pos / dur if dur else 0
                self.progress.create_rectangle(0, 0, int(w * pct), 8,
                                               fill=ACCENT, outline="")
                self.play_btn.config(text="❚❚" if snap.playing else "▶")
                self.state.config(text="● playing" if snap.playing else "❚❚ paused",
                                  fg=ACCENT if snap.playing else MUTED)
                if t.image_url != self._last_art:
                    self._last_art = t.image_url
                    self._load_art(t.image_url)
            else:
                self.title.config(text="Nothing playing")
                self.artist.config(text="")
                self.play_btn.config(text="▶")
                self.state.config(text="● idle", fg=MUTED)
            self.shuf_btn.config(fg=ACCENT if snap.shuffle else MUTED)
            self.rep_btn.config(fg=ACCENT if snap.repeat != "off" else MUTED)
            # queue
            q = snap.queue
            if self._list_mode == "queue":
                if len(q) != self.list_box.size():
                    self.list_box.delete(0, "end")
                    for i, tr in enumerate(q[:20]):
                        self.list_box.insert("end",
                                             f"{i + 1}. {tr.name} — {tr.artists}")
        except Exception:
            pass

    def _load_art(self, url):
        if not _HAS_PIL or not url:
            return
        def work():
            try:
                import io
                import requests
                r = requests.get(url, timeout=8)
                img = Image.open(io.BytesIO(r.content)).convert("RGB").resize((104, 104))
                ph = ImageTk.PhotoImage(img)
                self._photo = ph
                self.root.after(0, lambda: self.art.config(image=ph, text=""))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _toast(self, msg):
        try:
            self.root.after(0, lambda: self._toast_lbl.config(text=str(msg)))
        except Exception:
            pass

    # --------------------------------------------------------------- run
    def run(self):
        self._refresh_library()
        self.root.mainloop()

    def _on_close(self):
        self._stop.set()
        try:
            self.engine.shutdown()
        except Exception:
            pass
        self.root.destroy()

    def quit(self):
        self._on_close()


def _fmt(ms: int) -> str:
    total = max(0, int(ms) // 1000)
    return f"{total // 60}:{total % 60:02d}"


def run(engine, cfg: dict, demo: bool = False):
    PermifyGUI(engine, cfg, demo=demo).run()
