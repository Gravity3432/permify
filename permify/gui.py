"""Permify GUI — a windowed Spotify player.

Tabbed layout with a bottom player bar (Spotify-style). Built with tkinter
(stdlib, no extra deps). Talks to the same engine API as the terminal clients.
Distinct periwinkle-violet identity.

Made with heart by @johnthemailboy.
"""
from __future__ import annotations

import threading

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
PANEL2 = "#232836"
TEXT = "#e8e8ea"
MUTED = "#8a90a0"
ACCENT = "#7c5cff"     # periwinkle/violet — Permify's identity
ACCENT_DIM = "#5b43c0"
ACCENT_TEXT = "#ffffff"
GREEN = "#1db954"
LINE = "#262a33"

NAV = ["Home", "Search", "Library", "Queue", "Lyrics", "Devices", "Settings"]
NAV_GLYPH = ["⌂", "🔍", "▤", "▥", "♫", "⌬", "⚙"]


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
        self._search_results: list = []
        self._current_tab = "Home"
        self._liked_flag = False

        import tkinter as tk
        self.tk = tk
        self.root = tk.Tk()
        self.root.title("Permify" + ("  ·  demo" if demo else ""))
        self.root.geometry("980x640")
        self.root.configure(bg=BG)
        self.root.minsize(720, 500)

        self._build_widgets()
        self._bind_keys()

        self.engine.start(self._toast)
        self.snap: Snapshot = self.engine.snapshot()

        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI
    def _build_widgets(self) -> None:
        import tkinter as tk

        # --- left sidebar -------------------------------------------------
        side = tk.Frame(self.root, bg=SIDE, width=200)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        tk.Label(side, text="♪  PERMIFY", bg=SIDE, fg=ACCENT,
                 font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=16, pady=(16, 8))

        self.nav_buttons = {}
        for i, name in enumerate(NAV):
            b = tk.Button(side, text=f"{NAV_GLYPH[i]}  {name}", bg=SIDE, fg=MUTED,
                          bd=0, anchor="w", font=("Segoe UI", 11),
                          activebackground=SIDE, activeforeground=ACCENT,
                          command=lambda n=name: self.switch_tab(n))
            b.pack(fill="x", padx=8, pady=1)
            self.nav_buttons[name] = b

        tk.Frame(side, bg=LINE, height=1).pack(fill="x", padx=12, pady=8)

        tk.Label(side, text="YOUR LIBRARY", bg=SIDE, fg=ACCENT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=16, pady=(2, 4))
        self.lib = tk.Listbox(side, bg=SIDE, fg=TEXT, selectbackground=ACCENT,
                              selectforeground="#000", highlightthickness=0, bd=0,
                              font=("Segoe UI", 10))
        self.lib.pack(fill="both", expand=True, padx=8)
        self.lib.bind("<Double-Button-1>", lambda e: self._lib_open())
        tk.Button(side, text="↻ refresh", bg=SIDE, fg=TEXT, bd=0,
                  activebackground=ACCENT, command=self._refresh_library,
                  font=("Segoe UI", 9)).pack(fill="x", padx=12, pady=(6, 12))

        # --- main column ---------------------------------------------------
        main = tk.Frame(self.root, bg=BG)
        main.pack(side="right", fill="both", expand=True)

        # content area (panels stack in one cell; raise the active one)
        content = tk.Frame(main, bg=BG)
        content.pack(side="top", fill="both", expand=True)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self.panels = {}
        self._build_panels(content)

        # bottom player bar
        self._build_player_bar(main)

        self.switch_tab("Home")

    def _build_panels(self, content) -> None:
        import tkinter as tk
        for name in NAV:
            f = tk.Frame(content, bg=BG)
            f.grid(row=0, column=0, sticky="nsew")
            self.panels[name] = f
        self._build_home_panel(self.panels["Home"])
        self._build_search_panel(self.panels["Search"])
        self._build_library_panel(self.panels["Library"])
        self._build_queue_panel(self.panels["Queue"])
        self._build_lyrics_panel(self.panels["Lyrics"])
        self._build_devices_panel(self.panels["Devices"])
        self._build_settings_panel(self.panels["Settings"])

    # --- panels ------------------------------------------------------------
    def _build_home_panel(self, f) -> None:
        import tkinter as tk
        head = tk.Frame(f, bg=BG)
        head.pack(fill="x", padx=24, pady=(20, 6))
        self.art = tk.Label(head, bg=BG, text="♪", fg=ACCENT,
                            font=("Segoe UI", 52), width=7, height=3)
        self.art.pack(side="left")
        info = tk.Frame(head, bg=BG)
        info.pack(side="left", padx=18, fill="x", expand=True)
        self.title = tk.Label(info, text="Nothing playing", bg=BG, fg=TEXT,
                              font=("Segoe UI", 24, "bold"), anchor="w")
        self.title.pack(anchor="w")
        self.artist = tk.Label(info, text="", bg=BG, fg=MUTED,
                               font=("Segoe UI", 14), anchor="w")
        self.artist.pack(anchor="w")
        self.album = tk.Label(info, text="", bg=BG, fg=MUTED,
                              font=("Segoe UI", 11), anchor="w")
        self.album.pack(anchor="w")

        tk.Label(f, text="UP NEXT", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=24, pady=(14, 4))
        self.queue_box = tk.Listbox(f, bg=BG, fg=TEXT, highlightthickness=0, bd=0,
                                    font=("Segoe UI", 11), selectbackground=PANEL2)
        self.queue_box.pack(fill="both", expand=True, padx=24, pady=(2, 12))
        self.queue_box.bind("<Double-Button-1>", lambda e: self._queue_play())

    def _build_search_panel(self, f) -> None:
        import tkinter as tk
        srow = tk.Frame(f, bg=BG)
        srow.pack(fill="x", padx=24, pady=(20, 8))
        self.search_entry = tk.Entry(srow, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                                     bd=0, font=("Segoe UI", 12),
                                     highlightthickness=1, highlightbackground=PANEL,
                                     highlightcolor=ACCENT)
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.search_entry.bind("<Return>", lambda e: self._search())
        tk.Button(srow, text="Search", bg=ACCENT, fg=ACCENT_TEXT, bd=0,
                  font=("Segoe UI", 11, "bold"), command=self._search,
                  activebackground=ACCENT_DIM).pack(side="left", padx=(8, 0))
        self.results_box = tk.Listbox(f, bg=BG, fg=TEXT, highlightthickness=0, bd=0,
                                      font=("Segoe UI", 11), selectbackground=PANEL2)
        self.results_box.pack(fill="both", expand=True, padx=24, pady=(2, 12))
        self.results_box.bind("<Double-Button-1>", lambda e: self._play_search())

    def _build_library_panel(self, f) -> None:
        import tkinter as tk
        self.lib_header = tk.Label(f, text="Liked Songs", bg=BG, fg=ACCENT,
                                   font=("Segoe UI", 13, "bold"), anchor="w")
        self.lib_header.pack(fill="x", padx=24, pady=(20, 4))
        self.lib_box = tk.Listbox(f, bg=BG, fg=TEXT, highlightthickness=0, bd=0,
                                  font=("Segoe UI", 11), selectbackground=PANEL2)
        self.lib_box.pack(fill="both", expand=True, padx=24, pady=(2, 12))
        self.lib_box.bind("<Double-Button-1>", lambda e: self._play_search())

    def _build_queue_panel(self, f) -> None:
        import tkinter as tk
        tk.Label(f, text="UP NEXT", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 12, "bold"), anchor="w").pack(
            fill="x", padx=24, pady=(20, 4))
        self.queue_box2 = tk.Listbox(f, bg=BG, fg=TEXT, highlightthickness=0, bd=0,
                                     font=("Segoe UI", 11), selectbackground=PANEL2)
        self.queue_box2.pack(fill="both", expand=True, padx=24, pady=(2, 12))
        self.queue_box2.bind("<Double-Button-1>", lambda e: self._queue_play())

    def _build_lyrics_panel(self, f) -> None:
        import tkinter as tk
        tk.Label(f, text="LYRICS", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 12, "bold"), anchor="w").pack(
            fill="x", padx=24, pady=(20, 4))
        self.lyr = tk.Text(f, bg=BG, fg=TEXT, wrap="word", bd=0,
                           font=("Segoe UI", 12), highlightthickness=0,
                           insertbackground=TEXT)
        self.lyr.pack(fill="both", expand=True, padx=24, pady=(2, 12))
        self.lyr.insert("1.0", "Lyrics come here — coming soon in Phase 4! 🎤")
        self.lyr.config(state="disabled")

    def _build_devices_panel(self, f) -> None:
        import tkinter as tk
        tk.Label(f, text="DEVICES", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 12, "bold"), anchor="w").pack(
            fill="x", padx=24, pady=(20, 4))
        self.dev_status = tk.Label(f, text="", bg=BG, fg=MUTED, anchor="w",
                                   font=("Segoe UI", 10))
        self.dev_status.pack(fill="x", padx=24)
        tk.Label(f, text="", bg=BG, fg=MUTED, anchor="w",
                 font=("Segoe UI", 10)).pack(fill="x", padx=24)
        self.dev_list = tk.Listbox(f, bg=BG, fg=TEXT, highlightthickness=0, bd=0,
                                   font=("Segoe UI", 12), selectbackground=ACCENT,
                                   selectforeground="#000")
        self.dev_list.pack(fill="both", expand=True, padx=24, pady=(8, 8))
        self.dev_list.bind("<Double-Button-1>", lambda e: self._dev_select())
        btnrow = tk.Frame(f, bg=BG)
        btnrow.pack(fill="x", padx=24, pady=(0, 12))
        tk.Button(btnrow, text="↻ refresh devices", bg=PANEL, fg=TEXT, bd=0,
                  font=("Segoe UI", 10), command=self._dev_refresh,
                  activebackground=ACCENT).pack(side="left")
        tk.Label(f, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9),
                 anchor="w").pack(fill="x", padx=24, pady=(0, 12))

    def _build_settings_panel(self, f) -> None:
        import tkinter as tk
        tk.Label(f, text="SETTINGS", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 12, "bold"), anchor="w").pack(
            fill="x", padx=24, pady=(20, 4))
        body = tk.Frame(f, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(8, 12))

        def row(label, widget_cb):
            r = tk.Frame(body, bg=PANEL)
            r.pack(fill="x", pady=4, ipadx=12, ipady=7)
            tk.Label(r, text=label, bg=PANEL, fg=TEXT,
                     font=("Segoe UI", 11)).pack(side="left")
            widget_cb(r)

        def text_setting(label, key):
            def cb(r):
                e = tk.Entry(r, bg=PANEL2, fg=TEXT, insertbackground=TEXT,
                             bd=0, font=("Segoe UI", 10), width=22)
                e.insert(0, str(self.cfg.get(key, "")))
                e.pack(side="right")
                e.bind("<FocusOut>", lambda ev: self._save_text(key, e.get()))
            row(label, cb)

        def toggle_setting(label, key):
            self._settings_toggles = getattr(self, "_settings_toggles", {})
            def cb(r):
                var = self.tk.BooleanVar(value=bool(self.cfg.get(key, False)))
                self._settings_toggles[key] = var
                chk = self.tk.Checkbutton(r, variable=var, bg=PANEL, fg=TEXT,
                                          selectcolor=PANEL2, activebackground=PANEL,
                                          command=lambda k=key: self._save_toggle(k, var.get()))
                chk.pack(side="right")
            row(label, cb)

        text_setting("Device name shown in Spotify", "device_name")

        def volume_cb(r):
            self.set_vol = self.tk.Scale(r, from_=0, to=100, orient="horizontal",
                                         bg=PANEL, fg=TEXT, troughcolor=PANEL2,
                                         activebackground=ACCENT,
                                         highlightthickness=0, bd=0,
                                         command=self._save_volume)
            self.set_vol.set(self.volume)
            self.set_vol.pack(side="right")
        row("Default volume", volume_cb)
        toggle_setting("Desktop notifications", "notify")
        toggle_setting("Start on this device automatically", "auto_play")
        toggle_setting("Show shuffle by default", "shuffle")

        tk.Label(body, text="Keyboard shortcuts", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(14, 4))
        for s in ["Space  Play / Pause", "← / →   Seek −/+ 5s",
                  "Ctrl+1..7  Switch tab", "Ctrl+L  Open Settings",
                  "Ctrl+F  Focus search", "M  Mute"]:
            tk.Label(body, text="  " + s, bg=BG, fg=MUTED,
                     font=("Segoe UI", 10)).pack(anchor="w")

        tk.Label(body, text="Theme", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(14, 2))
        tk.Label(body, text="Periwinkle violet (#7c5cff) — a cooler theme picker is on the roadmap. ✨",
                 bg=BG, fg=MUTED, font=("Segoe UI", 10), wraplength=560,
                 justify="left").pack(anchor="w")

    # --- bottom player bar -------------------------------------------------
    def _build_player_bar(self, main) -> None:
        import tkinter as tk
        bar = tk.Frame(main, bg=SIDE, height=78)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        pad = 14

        # left: art + title/artist
        self.mini_art = tk.Label(bar, bg=SIDE, text="♪", fg=ACCENT,
                                 font=("Segoe UI", 18), width=3, height=1)
        self.mini_art.pack(side="left", padx=(pad, 6))
        minfo = tk.Frame(bar, bg=SIDE)
        minfo.pack(side="left", fill="y", pady=12)
        self.m_title = tk.Label(minfo, text="Nothing playing", bg=SIDE, fg=TEXT,
                                font=("Segoe UI", 11, "bold"), anchor="w")
        self.m_title.pack(anchor="w")
        self.m_artist = tk.Label(minfo, text="", bg=SIDE, fg=MUTED,
                                 font=("Segoe UI", 9), anchor="w")
        self.m_artist.pack(anchor="w")

        # right side: volume + shuffle/repeat + like
        right = tk.Frame(bar, bg=SIDE)
        right.pack(side="right", padx=pad)
        self.like_btn = tk.Button(right, text="♡", bg=SIDE, fg=MUTED, bd=0,
                                  font=("Segoe UI", 13), command=self._toggle_like,
                                  activebackground=SIDE)
        self.like_btn.pack(side="left", padx=6)
        self.shuf_btn = tk.Button(right, text="⇄", bg=SIDE, fg=MUTED, bd=0,
                                  font=("Segoe UI", 12), command=self._shuffle,
                                  activebackground=SIDE)
        self.shuf_btn.pack(side="left", padx=4)
        self.rep_btn = tk.Button(right, text="↻", bg=SIDE, fg=MUTED, bd=0,
                                 font=("Segoe UI", 12), command=self._repeat,
                                 activebackground=SIDE)
        self.rep_btn.pack(side="left", padx=4)
        self.m_vol = tk.Scale(right, from_=0, to=100, orient="horizontal", bg=SIDE,
                              fg=TEXT, highlightthickness=0, bd=0, width=10,
                              troughcolor=PANEL2, activebackground=ACCENT,
                              command=self._set_volume)
        self.m_vol.set(self.volume)
        self.m_vol.pack(side="left", padx=(8, 0))

        # center: transport + seek + time
        center = tk.Frame(bar, bg=SIDE)
        center.pack(side="left", fill="x", expand=True, padx=6)
        btns = tk.Frame(center, bg=SIDE)
        btns.pack()
        for txt, cmd, big in [("⏮", self._prev, False),
                              ("▶", self._toggle, True),
                              ("⏭", self._next, False)]:
            if big:
                self.play_btn = tk.Button(btns, text=txt, bg=ACCENT, fg=ACCENT_TEXT,
                                          bd=0, width=6, font=("Segoe UI", 14, "bold"),
                                          activebackground=ACCENT_DIM, command=cmd)
            else:
                b = tk.Button(btns, text=txt, bg=SIDE, fg=TEXT, bd=0, width=4,
                              font=("Segoe UI", 13), command=cmd,
                              activebackground=SIDE)
            (self.play_btn if big else b).pack(side="left", padx=4)
        self.time = tk.Label(center, text="0:00 / 0:00", bg=SIDE, fg=MUTED,
                             font=("Segoe UI", 8))
        self.time.pack()
        self.progress = tk.Canvas(center, height=6, bg=PANEL, highlightthickness=0, bd=0)
        self.progress.pack(fill="x", padx=6, pady=(2, 4))
        self.progress.bind("<Button-1>", self._click_seek)
        self.progress.bind("<B1-Motion>", self._click_seek)

    # ------------------------------------------------------------------ nav
    def switch_tab(self, name: str) -> None:
        self._current_tab = name
        for n, f in self.panels.items():
            if n == name:
                f.tkraise()
                self.nav_buttons[n].config(fg=ACCENT, font=("Segoe UI", 11, "bold"))
            else:
                self.nav_buttons[n].config(fg=MUTED, font=("Segoe UI", 11))
        if name == "Devices":
            self._dev_refresh()
        elif name == "Queue":
            self._sync_queue(self.queue_box2)

    # ----------------------------------------------------------------- keys
    def _bind_keys(self):
        self.root.bind("<space>", lambda e: self._toggle())
        self.root.bind("<Left>", lambda e: self._seek(-5))
        self.root.bind("<Right>", lambda e: self._seek(5))
        self.root.bind("<m>", lambda e: self._toggle_mute())
        self.root.bind("<Control-Key-f>", lambda e: (self.switch_tab("Search"),
                                                     self.search_entry.focus_set()))
        self.root.bind("<Control-Key-l>", lambda e: self.switch_tab("Settings"))
        for i, name in enumerate(NAV, start=1):
            self.root.bind(f"<Control-Key-{i}>", lambda e, n=name: self.switch_tab(n))

    # --------------------------------------------------------------- library
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
        self.switch_tab("Library")
        if item == "liked":
            self.lib_header.config(text="♥  Liked Songs")
            self._load_list(self.lib_box, self.engine.get_liked)
        elif item:
            self.lib_header.config(text=item.name)
            self._load_list(self.lib_box, lambda: self.engine.get_playlist_tracks(item))

    def _load_list(self, box, fetch):
        def work():
            try:
                tracks = fetch()
            except Exception:
                tracks = []
            def fill():
                self._search_results = tracks
                box.delete(0, "end")
                for t in tracks:
                    box.insert("end", f"{t.name}  —  {t.artists}")
            self.root.after(0, fill)
        threading.Thread(target=work, daemon=True).start()

    def _search(self):
        q = self.search_entry.get().replace("  Search…", "").strip()
        if not q:
            return
        self._load_list(self.results_box, lambda: self.engine.search(q))

    def _play_search(self):
        box = self.results_box if self._current_tab == "Search" else self.lib_box
        sel = box.curselection()
        if sel and sel[0] < len(self._search_results):
            tracks = self._search_results
            self.engine.play_tracks(tracks, sel[0], "Permify")

    def _queue_play(self):
        box = self.queue_box if self._current_tab == "Home" else self.queue_box2
        sel = box.curselection()
        if not sel:
            return
        try:
            self.engine.queue_play(sel[0])
        except Exception:
            pass

    # -------------------------------------------------------------- transport
    def _toggle(self):
        threading.Thread(target=self.engine.toggle, daemon=True).start()

    def _next(self):
        threading.Thread(target=self.engine.next, daemon=True).start()

    def _prev(self):
        threading.Thread(target=self.engine.prev, daemon=True).start()

    def _seek(self, delta_sec):
        self._seek_ms(int(self.snap.position_ms or 0) + delta_sec * 1000)

    def _seek_ms(self, ms):
        threading.Thread(target=self.engine.seek_ms, args=(int(ms),),
                         daemon=True).start()

    def _click_seek(self, e):
        try:
            w = max(1, e.widget.winfo_width())
            r = max(0.0, min(1.0, e.x / w))
            self._seek_ms(int((self.snap.duration_ms or 0) * r))
        except Exception:
            pass

    def _set_volume(self, v):
        self.volume = int(v)
        threading.Thread(target=self.engine.set_volume, args=(int(v),),
                         daemon=True).start()
        self._save_volume(v)

    def _save_volume(self, v):
        try:
            self.cfg["volume"] = int(v)
            from . import config as c
            c.save_config(self.cfg)
        except Exception:
            pass

    def _toggle_mute(self):
        self._set_volume(0 if self.volume > 0 else self.m_vol.get() or 60)

    def _shuffle(self):
        threading.Thread(target=self.engine.shuffle_toggle, daemon=True).start()

    def _repeat(self):
        threading.Thread(target=self.engine.repeat_cycle, daemon=True).start()

    def _toggle_like(self):
        t = self.snap.track
        if not t:
            return
        if hasattr(self.engine, "set_liked"):
            flag = not self._liked_flag
            def work():
                try:
                    self.engine.set_liked(t, flag)
                except Exception as e:
                    self._toast(f"like failed: {e}")
            threading.Thread(target=work, daemon=True).start()
            self._liked_flag = flag
            self.like_btn.config(text="♥" if flag else "♡",
                                 fg=GREEN if flag else MUTED)

    # --------------------------------------------------------------- settings
    def _save_text(self, key, value):
        try:
            self.cfg[key] = value
            from . import config as c
            c.save_config(self.cfg)
        except Exception:
            pass

    def _save_toggle(self, key, value):
        try:
            self.cfg[key] = value
            from . import config as c
            c.save_config(self.cfg)
        except Exception:
            pass

    # ---------------------------------------------------------------- devices
    def _dev_refresh(self):
        if not hasattr(self.engine, "devices"):
            self.dev_list.delete(0, "end")
            self.dev_list.insert("end", "No device control in this mode.")
            return
        def work():
            try:
                devs = self.engine.devices()
            except Exception:
                devs = []
            def fill():
                self._devices = devs
                self.dev_list.delete(0, "end")
                cur = None
                try:
                    cur = self.engine.device_label()
                except Exception:
                    cur = None
                if not devs:
                    self.dev_list.insert("end", "No Spotify devices found.")
                for d in devs:
                    active = "●" if (cur and d.get("name") == cur) else ""
                    self.dev_list.insert("end", f" {active} {d.get('name', '?')}")
                self.dev_status.config(text="Click a device to play there. Playing on this computer streams embedded audio.")
            self.root.after(0, fill)
        threading.Thread(target=work, daemon=True).start()

    def _dev_select(self):
        sel = self.dev_list.curselection()
        if not sel or not hasattr(self, "_devices") or sel[0] >= len(self._devices):
            return
        dev = self._devices[sel[0]]
        if hasattr(self.engine, "select_device"):
            def work():
                try:
                    self.engine.select_device(dev)
                    self._toast(f"Now playing on: {dev.get('name')}")
                except Exception as e:
                    self._toast(f"device error: {e}")
            threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------- poll
    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                self.snap = self.engine.snapshot()
                self._update()
            except Exception:
                pass
            self._stop.wait(0.5)

    def _sync_queue(self, box):
        q = self.snap.queue or []
        box.delete(0, "end")
        for i, tr in enumerate(q[:25]):
            box.insert("end", f"{i + 1}. {tr.name} — {tr.artists}")

    def _update(self):
        snap = self.snap
        try:
            if snap.track:
                t = snap.track
                # home panel
                self.title.config(text=t.name)
                self.artist.config(text=t.artists)
                self.album.config(text=t.album)
                # bottom bar
                self.m_title.config(text=t.name)
                self.m_artist.config(text=t.artists)
                pos, dur = int(snap.position_ms or 0), int(snap.duration_ms or 0)
                self.time.config(text=f"{_fmt(pos)} / {_fmt(dur)}")
                self.progress.delete("all")
                w = max(1, self.progress.winfo_width())
                pct = pos / dur if dur else 0
                self.progress.create_rectangle(0, 0, int(w * pct), 6,
                                               fill=ACCENT, outline="")
                self.play_btn.config(text="❚❚" if snap.playing else "▶")
                if t.image_url != self._last_art:
                    self._last_art = t.image_url
                    self._load_art(t.image_url)
            else:
                self.title.config(text="Nothing playing")
                self.artist.config(text="")
                self.m_title.config(text="Nothing playing")
                self.m_artist.config(text="")
                self.play_btn.config(text="▶")
            self.shuf_btn.config(fg=ACCENT if snap.shuffle else MUTED)
            self.rep_btn.config(fg=ACCENT if snap.repeat != "off" else MUTED)
            if snap.track and hasattr(self, "_liked_flag"):
                pass  # like state set on toggle
            # queue sync for current visible box
            if self._current_tab == "Home":
                self._sync_queue(self.queue_box)
            elif self._current_tab == "Queue":
                self._sync_queue(self.queue_box2)
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
                img = Image.open(io.BytesIO(r.content)).convert("RGB")
                big = img.resize((128, 128), Image.LANCZOS)
                small = img.resize((40, 40), Image.LANCZOS)
                self._photo = ImageTk.PhotoImage(big)
                self._photo_small = ImageTk.PhotoImage(small)
                self.root.after(0, lambda: self._set_art())
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _set_art(self):
        try:
            self.art.config(image=self._photo, text="")
            self.mini_art.config(image=self._photo_small, text="")
        except Exception:
            pass

    def _toast(self, msg):
        try:
            self.root.title(f"Permify — {msg}")
        except Exception:
            pass

    # ------------------------------------------------------------------- run
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
