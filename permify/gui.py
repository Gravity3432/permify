"""Permify GUI — a windowed Spotify player.

A performance-light, cover-art-driven desktop app. Tabbed navigation, a
bottom player bar, cover-tile library, rich track rows with clickable
artists, an artist page, an album view, category search, a Discover home,
and a blurred album-art backdrop. Periwinkle-violet identity.

Performance notes:
- UI updates are *change-driven*: widgets are only touched when the value
  actually changed (no re-render every poll tick).
- Volume is debounced (applied on release / throttled while dragging).
- Queue/lists are rebuilt only when their data actually changes.
- Network/engine calls run in background threads; the UI thread stays free.

Made with heart by @johnthemailboy.
"""
from __future__ import annotations

import threading

from . import ui
from .models import Snapshot

PAL = ui


class PermifyGUI:
    def __init__(self, engine, cfg: dict, demo: bool = False):
        self.engine = engine
        self.cfg = cfg
        self.demo = demo
        self.volume = int(cfg.get("volume", 60))
        self._stop = threading.Event()
        self._last = {}           # change-driven render cache
        self._queue_key = None
        self._vol_after = None
        self._user_drag = False
        self._playlists: list = []
        self._devices: list = []

        import tkinter as tk
        self.tk = tk
        self.root = tk.Tk()
        self.root.title("Permify" + ("  ·  demo" if demo else ""))
        self.root.geometry("1040x680")
        self.root.configure(bg=ui.BG)
        self.root.minsize(760, 520)
        self.images = ui.ImageCache()
        self.images.root = self.root

        self._build_widgets()
        self._bind_keys()

        self.engine.start(self._toast)
        self.snap: Snapshot = self.engine.snapshot()

        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.switch_tab("Home")
        self._refresh_library()
        self._load_home()

    # ------------------------------------------------------------------ UI
    def _build_widgets(self) -> None:
        import tkinter as tk

        # --- sidebar ----------------------------------------------------
        side = tk.Frame(self.root, bg=ui.SIDE, width=196)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="♪  PERMIFY", bg=ui.SIDE, fg=ui.ACCENT,
                 font=(ui.FONT, 15, "bold")).pack(anchor="w", padx=16, pady=(16, 10))

        self.nav_buttons = {}
        nav = [("Home", "⌂"), ("Search", "🔍"), ("Library", "▤"),
               ("Queue", "▥"), ("Lyrics", "♫"), ("Devices", "⌬"),
               ("Settings", "⚙")]
        self._nav_spec = nav
        for name, glyph in nav:
            b = tk.Button(side, text=f"{glyph}  {name}", bg=ui.SIDE, fg=ui.MUTED,
                          bd=0, anchor="w", font=(ui.FONT, 11),
                          activebackground=ui.SIDE, activeforeground=ui.ACCENT,
                          command=lambda n=name: self.switch_tab(n))
            b.pack(fill="x", padx=8, pady=1)
            self.nav_buttons[name] = b

        tk.Frame(side, bg=ui.LINE, height=1).pack(fill="x", padx=12, pady=8)
        tk.Label(side, text="YOUR LIBRARY", bg=ui.SIDE, fg=ui.ACCENT,
                 font=(ui.FONT, 9, "bold")).pack(anchor="w", padx=16, pady=(2, 4))
        self.lib = tk.Listbox(side, bg=ui.SIDE, fg=ui.TEXT, selectbackground=ui.ACCENT,
                              selectforeground="#000", highlightthickness=0, bd=0,
                              font=(ui.FONT, 10))
        self.lib.pack(fill="both", expand=True, padx=8)
        self.lib.bind("<Double-Button-1>", lambda e: self._lib_open())
        tk.Button(side, text="↻ refresh", bg=ui.SIDE, fg=ui.TEXT, bd=0,
                  activebackground=ui.ACCENT, command=self._refresh_all,
                  font=(ui.FONT, 9)).pack(fill="x", padx=12, pady=(6, 12))

        # --- main -------------------------------------------------------
        main = tk.Frame(self.root, bg=ui.BG)
        main.pack(side="right", fill="both", expand=True)

        content = tk.Frame(main, bg=ui.BG)
        content.pack(side="top", fill="both", expand=True)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self.panels = {}
        for name, _ in nav:
            f = tk.Frame(content, bg=ui.BG)
            f.grid(row=0, column=0, sticky="nsew")
            self.panels[name] = f
        # extra panels not in the nav (reached by clicking content)
        for name in ("Artist", "Album"):
            f = tk.Frame(content, bg=ui.BG)
            f.grid(row=0, column=0, sticky="nsew")
            self.panels[name] = f

        self._build_home(self.panels["Home"])
        self._build_search(self.panels["Search"])
        self._build_library(self.panels["Library"])
        self._build_queue(self.panels["Queue"])
        self._build_lyrics(self.panels["Lyrics"])
        self._build_devices(self.panels["Devices"])
        self._build_settings(self.panels["Settings"])
        self._build_artist(self.panels["Artist"])
        self._build_album(self.panels["Album"])

        self._build_player_bar(main)

    # ------------------------------------------------------------- panels
    def _build_home(self, f) -> None:
        import tkinter as tk
        self.home_bd = ui.Backdrop(f)
        self.home_bd.pack(fill="x")
        head = tk.Frame(self.home_bd, bg=ui.BG)
        self.home_bd.create_window(24, 16, window=head, anchor="nw")
        self.art = ui._ImageView(head, 96, seed="cover", bg=ui.BG)
        self.art.grid(row=0, column=0, rowspan=3, padx=(8, 16), pady=10)
        info = tk.Frame(head, bg=ui.BG)
        info.grid(row=0, column=1, sticky="w")
        tk.Label(info, text="NOW PLAYING", bg=ui.BG, fg=ui.ACCENT,
                 font=(ui.FONT, 9, "bold")).pack(anchor="w")
        self.title = tk.Label(info, text="Nothing playing", bg=ui.BG, fg=ui.TEXT,
                              font=(ui.FONT, 22, "bold"), anchor="w")
        self.title.pack(anchor="w")
        self.artist = tk.Label(info, text="", bg=ui.BG, fg=ui.MUTED,
                               font=(ui.FONT, 13), anchor="w")
        self.artist.pack(anchor="w")
        self.album = tk.Label(info, text="", bg=ui.BG, fg=ui.MUTED,
                              font=(ui.FONT, 10), anchor="w")
        self.album.pack(anchor="w")

        body = tk.Frame(f, bg=ui.BG)
        body.pack(fill="both", expand=True, padx=20, pady=8)
        self.home_scroll = ui.ScrollFrame(body)
        self.home_scroll.pack(fill="both", expand=True)

        self.home_playlists = ui.TileGrid(self.home_scroll.body, cols=5, tile_size=118)
        self.home_top_tracks = ui.TrackList(self.home_scroll.body)
        self.home_artists = ui.TileGrid(self.home_scroll.body, cols=6, tile_size=92)
        self.home_recent = ui.TrackList(self.home_scroll.body)
        self._section("YOUR PLAYLISTS", self.home_playlists)
        self._section("MOST PLAYED", self.home_top_tracks)
        self._section("YOUR ARTISTS", self.home_artists)
        self._section("RECENTLY PLAYED", self.home_recent)
        self.home_top_tracks.on_play = self._play_track
        self.home_recent.on_play = self._play_track
        self.home_top_tracks.on_artist = self._open_artist
        self.home_recent.on_artist = self._open_artist

    def _section(self, label, widget):
        import tkinter as tk
        tk.Label(self.home_scroll.body, text=label, bg=ui.BG, fg=ui.ACCENT,
                 font=(ui.FONT, 12, "bold"), anchor="w").pack(fill="x", pady=(14, 2))
        widget.pack(fill="x")

    def _build_search(self, f) -> None:
        import tkinter as tk
        srow = tk.Frame(f, bg=ui.BG)
        srow.pack(fill="x", padx=20, pady=(18, 4))
        self.search_entry = tk.Entry(srow, bg=ui.PANEL, fg=ui.TEXT,
                                     insertbackground=ui.TEXT, bd=0,
                                     font=(ui.FONT, 12), highlightthickness=1,
                                     highlightbackground=ui.PANEL,
                                     highlightcolor=ui.ACCENT)
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.search_entry.bind("<Return>", lambda e: self._search())
        self.search_entry.bind("<KeyRelease>", self._search_debounce)
        self.search_entry.insert(0, "")
        tk.Button(srow, text="Search", bg=ui.ACCENT, fg=ui.ACCENT_TEXT, bd=0,
                  font=(ui.FONT, 10, "bold"), command=self._search,
                  activebackground=ui.ACCENT_DIM).pack(side="left", padx=(8, 0))

        trow = tk.Frame(f, bg=ui.BG)
        trow.pack(fill="x", padx=20, pady=(8, 4))
        self.search_tabs = {}
        for i, name in enumerate(["All", "Tracks", "Artists", "Albums", "Playlists"]):
            b = tk.Button(trow, text=name, bg=ui.BG, fg=ui.MUTED, bd=0,
                          font=(ui.FONT, 10), command=lambda n=name: self._search_cat(n),
                          activebackground=ui.BG)
            b.pack(side="left", padx=(0, 10))
            self.search_tabs[name] = b

        self.search_area = tk.Frame(f, bg=ui.BG)
        self.search_area.pack(fill="both", expand=True, padx=20, pady=(4, 12))
        self.search_results = ui.TrackList(self.search_area)
        self.search_results.pack(fill="both", expand=True)
        self.search_results.on_play = self._play_track
        self.search_results.on_artist = self._open_artist
        self.search_results.on_like = self._like_track
        self._search_pane = "tracks"
        self._search_cat("All", redraw=False)

    def _build_library(self, f) -> None:
        self.lib_stack = ui.ScrollFrame(f)
        self.lib_stack.pack(fill="both", expand=True, padx=20, pady=12)
        self.library_grid = ui.TileGrid(self.lib_stack.body, cols=5, tile_size=120)
        self.library_grid.pack(fill="x")

    def _build_queue(self, f) -> None:
        import tkinter as tk
        tk.Label(f, text="UP NEXT", bg=ui.BG, fg=ui.ACCENT,
                 font=(ui.FONT, 12, "bold"), anchor="w").pack(
            fill="x", padx=20, pady=(18, 4))
        self.queue_list = ui.TrackList(f)
        self.queue_list.pack(fill="both", expand=True, padx=20, pady=(2, 12))
        self.queue_list.on_play = self._play_queue
        self.queue_list.on_artist = self._open_artist
        self.queue_list.on_like = self._like_track

    def _build_lyrics(self, f) -> None:
        import tkinter as tk
        tk.Label(f, text="LYRICS", bg=ui.BG, fg=ui.ACCENT,
                 font=(ui.FONT, 12, "bold"), anchor="w").pack(
            fill="x", padx=20, pady=(18, 4))
        self.lyr = tk.Text(f, bg=ui.BG, fg=ui.TEXT, wrap="word", bd=0,
                           font=(ui.FONT, 12), highlightthickness=0,
                           insertbackground=ui.TEXT)
        self.lyr.pack(fill="both", expand=True, padx=20, pady=(2, 12))
        self.lyr.insert("1.0", "Lyrics appear here when a track is playing.")
        self.lyr.config(state="disabled")

    def _build_devices(self, f) -> None:
        import tkinter as tk
        tk.Label(f, text="DEVICES", bg=ui.BG, fg=ui.ACCENT,
                 font=(ui.FONT, 12, "bold"), anchor="w").pack(
            fill="x", padx=20, pady=(18, 2))
        self.dev_status = tk.Label(f, text="", bg=ui.BG, fg=ui.MUTED, anchor="w",
                                   font=(ui.FONT, 10))
        self.dev_status.pack(fill="x", padx=20)
        self.dev_list = tk.Listbox(f, bg=ui.BG, fg=ui.TEXT, highlightthickness=0,
                                   bd=0, font=(ui.FONT, 12), selectbackground=ui.ACCENT,
                                   selectforeground="#000")
        self.dev_list.pack(fill="both", expand=True, padx=20, pady=(8, 8))
        self.dev_list.bind("<Double-Button-1>", lambda e: self._dev_select())
        tk.Button(f, text="↻ refresh devices", bg=ui.PANEL, fg=ui.TEXT, bd=0,
                  font=(ui.FONT, 10), command=self._dev_refresh,
                  activebackground=ui.ACCENT).pack(anchor="w", padx=20, pady=(0, 12))

    def _build_settings(self, f) -> None:
        import tkinter as tk
        tk.Label(f, text="SETTINGS", bg=ui.BG, fg=ui.ACCENT,
                 font=(ui.FONT, 12, "bold"), anchor="w").pack(
            fill="x", padx=20, pady=(18, 4))
        body = tk.Frame(f, bg=ui.BG)
        body.pack(fill="both", expand=True, padx=20, pady=(8, 12))

        def row(label, wcb):
            r = tk.Frame(body, bg=ui.PANEL)
            r.pack(fill="x", pady=4, ipadx=12, ipady=7)
            tk.Label(r, text=label, bg=ui.PANEL, fg=ui.TEXT,
                     font=(ui.FONT, 11)).pack(side="left")
            wcb(r)

        def text_setting(label, key):
            def cb(r):
                e = tk.Entry(r, bg=ui.PANEL2, fg=ui.TEXT, insertbackground=ui.TEXT,
                             bd=0, font=(ui.FONT, 10), width=22)
                e.insert(0, str(self.cfg.get(key, "")))
                e.pack(side="right")
                e.bind("<FocusOut>", lambda ev: self._save_cfg(key, e.get()))
            row(label, cb)

        def toggle_setting(label, key):
            def cb(r):
                var = tk.BooleanVar(value=bool(self.cfg.get(key, False)))
                def on():
                    self._save_cfg(key, var.get())
                chk = tk.Checkbutton(r, variable=var, bg=ui.PANEL, fg=ui.TEXT,
                                     selectcolor=ui.PANEL2, activebackground=ui.PANEL,
                                     command=on)
                chk.pack(side="right")
            row(label, cb)

        text_setting("Device name shown in Spotify", "device_name")
        row("Default volume", self._settings_vol_row)
        toggle_setting("Desktop notifications", "notify")
        toggle_setting("Start playing automatically", "auto_play")
        toggle_setting("Shuffle by default", "shuffle")
        toggle_setting("Keep mini-player on top", "mini_on_top")

        tk.Label(body, text="Keyboard shortcuts", bg=ui.BG, fg=ui.ACCENT,
                 font=(ui.FONT, 10, "bold")).pack(anchor="w", pady=(14, 4))
        for s in ["Space  Play / Pause", "← / →   Seek −/+ 5s", "M  Mute",
                  "Ctrl+1..7  Switch tab", "Ctrl+F  Search", "Ctrl+L  Settings"]:
            tk.Label(body, text="  " + s, bg=ui.BG, fg=ui.MUTED,
                     font=(ui.FONT, 10)).pack(anchor="w")

        tk.Label(body, text="Theme", bg=ui.BG, fg=ui.ACCENT,
                 font=(ui.FONT, 10, "bold")).pack(anchor="w", pady=(14, 2))
        tk.Label(body, text="Periwinkle violet (#7c5cff). A 'make it cooler' theme pass is planned.",
                 bg=ui.BG, fg=ui.MUTED, font=(ui.FONT, 10), wraplength=560,
                 justify="left").pack(anchor="w")

    def _settings_vol_row(self, r):
        self.set_vol = self.tk.Scale(r, from_=0, to=100, orient="horizontal",
                                     bg=ui.PANEL, fg=ui.TEXT, troughcolor=ui.PANEL2,
                                     activebackground=ui.ACCENT, highlightthickness=0,
                                     bd=0, command=self._vol_changed)
        self.set_vol.set(self.volume)
        self.set_vol.bind("<ButtonRelease-1>", lambda e: self._vol_commit())
        self.set_vol.pack(side="right")

    def _build_artist(self, f) -> None:
        import tkinter as tk
        top = tk.Frame(f, bg=ui.BG)
        top.pack(fill="x", padx=20, pady=(12, 4))
        tk.Button(top, text="‹  Back", bg=ui.BG, fg=ui.ACCENT, bd=0,
                  font=(ui.FONT, 10, "bold"), command=lambda: self.switch_tab("Home"),
                  activebackground=ui.BG).pack(anchor="w")
        head = tk.Frame(f, bg=ui.PANEL)
        head.pack(fill="x", padx=20, pady=4)
        self.art_avatar = ui._ImageView(head, 88, seed="artist", bg=ui.PANEL)
        self.art_avatar.grid(row=0, column=0, rowspan=2, padx=(16, 16), pady=14)
        ncol = tk.Frame(head, bg=ui.PANEL)
        ncol.grid(row=0, column=1, sticky="w")
        self.art_name = tk.Label(ncol, text="", bg=ui.PANEL, fg=ui.TEXT,
                                 font=(ui.FONT, 20, "bold"), anchor="w")
        self.art_name.pack(anchor="w")
        self.art_fol = tk.Label(ncol, text="", bg=ui.PANEL, fg=ui.MUTED,
                                font=(ui.FONT, 11), anchor="w")
        self.art_fol.pack(anchor="w")
        bcol = tk.Frame(head, bg=ui.PANEL)
        bcol.grid(row=0, column=2, sticky="e", padx=16)
        self.art_play = tk.Button(bcol, text="▶  Play", bg=ui.ACCENT, fg=ui.ACCENT_TEXT,
                                  bd=0, font=(ui.FONT, 10, "bold"),
                                  activebackground=ui.ACCENT_DIM, command=self._play_artist)
        self.art_play.grid(row=0, column=0, padx=4)
        self.art_follow = tk.Button(bcol, text="Follow", bg=ui.PANEL, fg=ui.TEXT, bd=0,
                                    font=(ui.FONT, 10), activebackground=ui.PANEL2,
                                    command=self._follow_artist)
        self.art_follow.grid(row=0, column=1, padx=4)

        body = tk.Frame(f, bg=ui.BG)
        body.pack(fill="both", expand=True, padx=20, pady=8)
        self.artist_scroll = ui.ScrollFrame(body)
        self.artist_scroll.pack(fill="both", expand=True)
        tk.Label(self.artist_scroll.body, text="POPULAR", bg=ui.BG, fg=ui.ACCENT,
                 font=(ui.FONT, 12, "bold"), anchor="w").pack(fill="x", pady=(10, 2))
        self.artist_top = ui.TrackList(self.artist_scroll.body)
        self.artist_top.pack(fill="x")
        self.artist_top.on_play = self._play_track
        self.artist_top.on_artist = self._open_artist
        self.artist_top.on_like = self._like_track
        tk.Label(self.artist_scroll.body, text="ALBUMS", bg=ui.BG, fg=ui.ACCENT,
                 font=(ui.FONT, 12, "bold"), anchor="w").pack(fill="x", pady=(14, 2))
        self.artist_albums = ui.TileGrid(self.artist_scroll.body, cols=5, tile_size=120)
        self.artist_albums.pack(fill="x")

    def _build_album(self, f) -> None:
        import tkinter as tk
        top = tk.Frame(f, bg=ui.BG)
        top.pack(fill="x", padx=20, pady=(12, 4))
        tk.Button(top, text="‹  Back", bg=ui.BG, fg=ui.ACCENT, bd=0,
                  font=(ui.FONT, 10, "bold"), command=lambda: self.switch_tab("Home"),
                  activebackground=ui.BG).pack(anchor="w")
        head = tk.Frame(f, bg=ui.BG)
        head.pack(fill="x", padx=20, pady=6)
        self.alb_cover = ui._ImageView(head, 120, seed="album", bg=ui.BG)
        self.alb_cover.grid(row=0, column=0, rowspan=2, padx=(0, 18))
        ncol = tk.Frame(head, bg=ui.BG)
        ncol.grid(row=0, column=1, sticky="w")
        self.alb_name = tk.Label(ncol, text="", bg=ui.BG, fg=ui.TEXT,
                                 font=(ui.FONT, 20, "bold"), anchor="w")
        self.alb_name.pack(anchor="w")
        self.alb_meta = tk.Label(ncol, text="", bg=ui.BG, fg=ui.MUTED,
                                 font=(ui.FONT, 11), anchor="w")
        self.alb_meta.pack(anchor="w")
        tk.Button(ncol, text="▶  Play album", bg=ui.ACCENT, fg=ui.ACCENT_TEXT,
                  bd=0, font=(ui.FONT, 10, "bold"), activebackground=ui.ACCENT_DIM,
                  command=self._play_album).pack(anchor="w", pady=(8, 0))
        self.album_tracks = ui.TrackList(f)
        self.album_tracks.pack(fill="both", expand=True, padx=20, pady=(6, 12))
        self.album_tracks.on_play = self._play_track
        self.album_tracks.on_artist = self._open_artist
        self.album_tracks.on_like = self._like_track

    # ------------------------------------------------------- player bar
    def _build_player_bar(self, main) -> None:
        import tkinter as tk
        bar = tk.Frame(main, bg=ui.SIDE, height=76)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        pad = 14

        self.mini_art = ui._ImageView(bar, 52, seed="mini", bg=ui.SIDE)
        self.mini_art.pack(side="left", padx=(pad, 10), pady=10)
        minfo = tk.Frame(bar, bg=ui.SIDE)
        minfo.pack(side="left", fill="y", pady=12)
        self.m_title = tk.Label(minfo, text="Nothing playing", bg=ui.SIDE, fg=ui.TEXT,
                                font=(ui.FONT, 11, "bold"), anchor="w")
        self.m_title.pack(anchor="w")
        self.m_artist = tk.Label(minfo, text="", bg=ui.SIDE, fg=ui.MUTED,
                                 font=(ui.FONT, 9), anchor="w")
        self.m_artist.pack(anchor="w")

        right = tk.Frame(bar, bg=ui.SIDE)
        right.pack(side="right", padx=pad)
        self.like_btn = tk.Button(right, text="♡", bg=ui.SIDE, fg=ui.MUTED, bd=0,
                                  font=(ui.FONT, 14), command=self._toggle_like,
                                  activebackground=ui.SIDE)
        self.like_btn.pack(side="left", padx=6)
        self.shuf_btn = tk.Button(right, text="⇄", bg=ui.SIDE, fg=ui.MUTED, bd=0,
                                  font=(ui.FONT, 13), command=self._shuffle,
                                  activebackground=ui.SIDE)
        self.shuf_btn.pack(side="left", padx=4)
        self.rep_btn = tk.Button(right, text="↻", bg=ui.SIDE, fg=ui.MUTED, bd=0,
                                 font=(ui.FONT, 13), command=self._repeat,
                                 activebackground=ui.SIDE)
        self.rep_btn.pack(side="left", padx=4)
        self.m_vol = tk.Scale(right, from_=0, to=100, orient="horizontal", bg=ui.SIDE,
                              fg=ui.TEXT, highlightthickness=0, bd=0, width=10,
                              troughcolor=ui.PANEL2, activebackground=ui.ACCENT,
                              command=self._vol_changed)
        self.m_vol.set(self.volume)
        self.m_vol.bind("<ButtonRelease-1>", lambda e: self._vol_commit())
        self.m_vol.pack(side="left", padx=(8, 0))

        center = tk.Frame(bar, bg=ui.SIDE)
        center.pack(side="left", fill="x", expand=True, padx=6)
        btns = tk.Frame(center, bg=ui.SIDE)
        btns.pack()
        for txt, cmd, big in [("⏮", self._prev, False),
                              ("▶", self._toggle, True),
                              ("⏭", self._next, False)]:
            if big:
                self.play_btn = tk.Button(btns, text=txt, bg=ui.ACCENT, fg=ui.ACCENT_TEXT,
                                          bd=0, width=6, font=(ui.FONT, 14, "bold"),
                                          activebackground=ui.ACCENT_DIM, command=cmd)
            else:
                b = tk.Button(btns, text=txt, bg=ui.SIDE, fg=ui.TEXT, bd=0, width=4,
                              font=(ui.FONT, 13), command=cmd, activebackground=ui.SIDE)
            (self.play_btn if big else b).pack(side="left", padx=4)
        self.time = tk.Label(center, text="0:00 / 0:00", bg=ui.SIDE, fg=ui.MUTED,
                             font=(ui.FONT, 8))
        self.time.pack()
        self.progress = tk.Canvas(center, height=6, bg=ui.PANEL, highlightthickness=0, bd=0)
        self.progress.pack(fill="x", padx=6, pady=(2, 4))
        self.progress.bind("<Button-1>", self._click_seek)
        self.progress.bind("<B1-Motion>", self._click_seek)

    # ------------------------------------------------------------------ nav
    def switch_tab(self, name: str) -> None:
        self._current_tab = name
        for n, f in self.panels.items():
            if n == name:
                f.tkraise()
                self.nav_buttons.get(n, None) and \
                    self.nav_buttons[n].config(fg=ui.ACCENT, font=(ui.FONT, 11, "bold"))
            else:
                if n in self.nav_buttons:
                    self.nav_buttons[n].config(fg=ui.MUTED, font=(ui.FONT, 11))
        if name == "Devices":
            self._dev_refresh()
        elif name == "Lyrics":
            self._refresh_lyrics()
        elif name == "Queue":
            self._sync_queue_now()

    # ----------------------------------------------------------------- keys
    def _bind_keys(self):
        self.root.bind("<space>", lambda e: self._toggle())
        self.root.bind("<Left>", lambda e: self._seek(-5))
        self.root.bind("<Right>", lambda e: self._seek(5))
        self.root.bind("<m>", lambda e: self._toggle_mute())
        self.root.bind("<Control-Key-f>", lambda e: (self.switch_tab("Search"),
                                                     self.search_entry.focus_set()))
        self.root.bind("<Control-Key-l>", lambda e: self.switch_tab("Settings"))
        for i, (name, _g) in enumerate(self._nav_spec, start=1):
            self.root.bind(f"<Control-Key-{i}>", lambda e, n=name: self.switch_tab(n))

    # ------------------------------------------------------------ library
    def _refresh_all(self):
        self._refresh_library()
        self._load_home()

    def _refresh_library(self):
        def work():
            try:
                pls = self.engine.get_playlists()
            except Exception:
                pls = []
            self.root.after(0, lambda: self._fill_library(pls))
        threading.Thread(target=work, daemon=True).start()

    def _fill_library(self, pls):
        self._playlists = pls
        self.lib.delete(0, "end")
        self.lib.insert("end", "♥  Liked Songs")
        for p in pls:
            self.lib.insert("end", f"  {p.name}")
        items = [{"label": "Liked Songs", "seed": "liked", "url": "",
                  "command": lambda: self._open_playlist("liked", "♥  Liked Songs")}]
        for p in pls:
            items.append({"label": p.name, "url": p.image_url, "seed": p.name,
                          "sub": f"{p.count} tracks",
                          "command": lambda p=p: self._open_playlist(p, p.name)})
        self.library_grid.set_items(items, self.images)

    def _lib_open(self):
        sel = self.lib.curselection()
        if not sel:
            return
        if sel[0] == 0:
            self._open_playlist("liked", "♥  Liked Songs")
        elif sel[0] - 1 < len(self._playlists):
            p = self._playlists[sel[0] - 1]
            self._open_playlist(p, p.name)

    def _open_playlist(self, pl, name):
        def work():
            try:
                if pl == "liked":
                    tracks = self.engine.get_liked()
                else:
                    tracks = self.engine.get_playlist_tracks(pl)
            except Exception:
                tracks = []
            def fill():
                self.switch_tab("Library")
                self.library_grid.clear()
                tl = ui.TrackList(self.lib_stack.body)
                tl.pack(fill="both", expand=True)
                tl.on_play = self._play_track
                tl.on_artist = self._open_artist
                tl.on_like = self._like_track
                self._cur_library_list = tl
                tl.set_items(tracks, self.images)
            self.root.after(0, fill)
        threading.Thread(target=work, daemon=True).start()

    # ----------------------------------------------------------------- home
    def _load_home(self):
        def work():
            try:
                pls = self.engine.get_playlists()
                tops = self.engine.top_tracks()
                arts = self.engine.top_artists()
                recent = self.engine.recently_played()
            except Exception:
                pls, tops, arts, recent = [], [], [], []
            self.root.after(0, lambda: self._fill_home(pls, tops, arts, recent))
        threading.Thread(target=work, daemon=True).start()

    def _fill_home(self, pls, tops, arts, recent):
        p_items = [{"label": "Liked Songs", "seed": "liked", "url": "",
                    "command": lambda: self._open_playlist("liked", "Liked Songs")}]
        for p in pls:
            p_items.append({"label": p.name, "url": p.image_url, "seed": p.name,
                            "command": lambda p=p: self._open_playlist(p, p.name)})
        self.home_playlists.set_items(p_items, self.images)
        self.home_top_tracks.set_items(tops, self.images)
        a_items = [{"label": a.name, "url": a.image_url, "seed": a.name,
                    "command": lambda a=a: self._open_artist(a)} for a in arts]
        self.home_artists.set_items(a_items, self.images)
        self.home_recent.set_items(recent, self.images)

    # ------------------------------------------------------------- search
    def _search_debounce(self, e=None):
        if getattr(self, "_search_after", None):
            self.root.after_cancel(self._search_after)
        self._search_after = self.root.after(300, self._search)

    def _search(self):
        q = self.search_entry.get().strip()
        if not q:
            self.search_results.clear()
            return
        self._search_cat(self._search_cat_name, query=q)

    def _search_cat(self, name, query=None, redraw=True):
        self._search_cat_name = name
        for n, b in self.search_tabs.items():
            b.config(fg=ui.ACCENT if n == name else ui.MUTED,
                     font=(ui.FONT, 10, "bold") if n == name else (ui.FONT, 10))
        q = query if query is not None else self.search_entry.get().strip()
        if not q:
            if name == "All":
                self._populate_tracks([])
            return
        def work():
            try:
                res = self.engine.search_all(q)
            except Exception:
                res = {}
            def fill():
                cat = name
                if cat == "Tracks" or cat == "All":
                    self._populate_tracks(res.get("tracks") or [])
                elif cat == "Artists":
                    self._populate_artists(res.get("artists") or [])
                elif cat == "Albums":
                    self._populate_albums(res.get("albums") or [])
                elif cat == "Playlists":
                    self._populate_playlists(res.get("playlists") or [])
            self.root.after(0, fill)
        threading.Thread(target=work, daemon=True).start()

    def _populate_tracks(self, tracks):
        self.search_results.pack(fill="both", expand=True)
        self.search_results.set_items(tracks, self.images)
        self._search_pane = "tracks"

    def _populate_artists(self, artists):
        self.search_results.pack_forget()
        g = ui.TileGrid(self.search_area, cols=5, tile_size=130)
        g.pack(fill="both", expand=True)
        items = [{"label": a.name, "url": a.image_url, "seed": a.name,
                  "command": lambda a=a: self._open_artist(a)} for a in artists]
        g.set_items(items, self.images)
        self._search_pane = "artists"

    def _populate_albums(self, albums):
        self.search_results.pack_forget()
        g = ui.TileGrid(self.search_area, cols=5, tile_size=130)
        g.pack(fill="both", expand=True)
        items = [{"label": a.name, "url": a.image_url, "seed": a.name,
                  "sub": a.artists, "command": lambda a=a: self._open_album(a)}
                 for a in albums]
        g.set_items(items, self.images)
        self._search_pane = "albums"

    def _populate_playlists(self, playlists):
        self.search_results.pack_forget()
        g = ui.TileGrid(self.search_area, cols=5, tile_size=130)
        g.pack(fill="both", expand=True)
        items = [{"label": p.name, "url": p.image_url, "seed": p.name,
                  "sub": f"{p.count} tracks",
                  "command": lambda p=p: self._open_playlist(p, p.name)}
                 for p in playlists]
        g.set_items(items, self.images)
        self._search_pane = "playlists"

    # ------------------------------------------------------------ artist
    def _open_artist(self, artist):
        self.switch_tab("Artist")
        self.art_name.config(text=getattr(artist, "name", "?"))
        self.images.attach(self.art_avatar, getattr(artist, "image_url", None), 88)
        def work():
            try:
                info = self.engine.artist_info(artist)
                albums = self.engine.artist_albums(artist)
                tops = self.engine.artist_top(artist)
                following = self.engine.is_following_artist(artist)
            except Exception:
                info, albums, tops, following = artist, [], [], False
            def fill():
                self.images.attach(self.art_avatar, info.image_url, 88)
                fol = f"{_num(info.followers)} followers" if info.followers else ""
                self.art_fol.config(text=fol)
                self.art_follow.config(text="Following ✓" if following else "Follow",
                                       fg=ui.ACCENT if following else ui.TEXT)
                self._cur_artist = info
                self._artist_tops = tops
                items = [{"label": a.name, "url": a.image_url, "seed": a.name,
                          "sub": a.year, "command": lambda a=a: self._open_album(a)}
                         for a in albums]
                self.artist_albums.set_items(items, self.images)
                self.artist_top.set_items(tops, self.images)
            self.root.after(0, fill)
        threading.Thread(target=work, daemon=True).start()

    def _play_artist(self):
        tops = getattr(self, "_artist_tops", None)
        tr = getattr(self, "_cur_artist", None)
        if tops and tr:
            def work():
                try:
                    self.engine.play_tracks(tops, 0, tr.name)
                except Exception:
                    pass
            threading.Thread(target=work, daemon=True).start()

    def _follow_artist(self):
        a = getattr(self, "_cur_artist", None)
        if not a:
            return
        now = "Following ✓" in self.art_follow["text"]
        def work():
            try:
                self.engine.follow_artist(a, not now)
            except Exception:
                pass
            def fill():
                self.art_follow.config(text="Unfollow" if not now else "Follow",
                                       fg=ui.TEXT if not now else ui.ACCENT)
            self.root.after(0, fill)
        threading.Thread(target=work, daemon=True).start()

    # -------------------------------------------------------------- album
    def _open_album(self, album):
        self.switch_tab("Album")
        self.alb_name.config(text=getattr(album, "name", "?"))
        self.images.attach(self.alb_cover, getattr(album, "image_url", None), 120)
        self.alb_meta.config(text=f"{getattr(album, 'artists', '')} · {getattr(album, 'year', '')}")
        self._cur_album = album
        def work():
            try:
                tracks = self.engine.album_tracks(album.id, album)
            except Exception:
                tracks = []
            def fill():
                self.album_tracks.set_items(tracks, self.images)
            self.root.after(0, fill)
        threading.Thread(target=work, daemon=True).start()

    def _play_album(self):
        a = getattr(self, "_cur_album", None)
        if a:
            def work():
                try:
                    tracks = self.engine.album_tracks(a.id, a)
                except Exception:
                    tracks = []
                if tracks:
                    self.engine.play_tracks(tracks, 0, a.name)
            threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- playback
    def _play_track(self, track):
        def work():
            try:
                self.engine.play_resume(track.uri, track.name, 0)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _play_queue(self, track):
        q = self.snap.queue or []
        idx = next((i for i, t in enumerate(q) if t.uri == track.uri), None)
        if idx is not None:
            threading.Thread(target=lambda: self._safe_queue_play(idx),
                             daemon=True).start()

    def _safe_queue_play(self, idx):
        try:
            self.engine.queue_play(idx)
        except Exception:
            pass

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

    # volume debounced
    def _vol_changed(self, v):
        self.volume = int(v)
        if self._vol_after:
            try:
                self.root.after_cancel(self._vol_after)
            except Exception:
                pass
        self._vol_after = self.root.after(200, self._vol_apply)

    def _vol_apply(self):
        self._vol_after = None
        threading.Thread(target=self.engine.set_volume, args=(self.volume,),
                         daemon=True).start()

    def _vol_commit(self):
        if self._vol_after:
            try:
                self.root.after_cancel(self._vol_after)
            except Exception:
                pass
            self._vol_after = None
        threading.Thread(target=self.engine.set_volume, args=(self.volume,),
                         daemon=True).start()
        self._save_cfg("volume", self.volume)

    def _toggle_mute(self):
        self._set_volume_target(0 if self.volume > 0 else self.m_vol.get())

    def _set_volume_target(self, v):
        self.volume = int(v)
        self.m_vol.set(v)
        self._vol_commit()

    def _shuffle(self):
        threading.Thread(target=self.engine.shuffle_toggle, daemon=True).start()

    def _repeat(self):
        threading.Thread(target=self.engine.repeat_cycle, daemon=True).start()

    def _like_track(self, track):
        if hasattr(self.engine, "set_liked"):
            flag = not track.liked
            def work():
                try:
                    self.engine.set_liked(track, flag)
                except Exception as e:
                    self._toast(str(e))
            threading.Thread(target=work, daemon=True).start()

    def _toggle_like(self):
        t = self.snap.track
        if t:
            self._like_track(t)

    # ----------------------------------------------------------- settings
    def _save_cfg(self, key, value):
        try:
            self.cfg[key] = value
            from . import config as c
            c.save_config(self.cfg)
        except Exception:
            pass

    # ------------------------------------------------------------ devices
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
                if not devs:
                    self.dev_list.insert("end", "No Spotify devices found.")
                for d in devs:
                    mark = "● " if d.get("active") else "  "
                    self.dev_list.insert("end", f"{mark}{d.get('name','?')}")
                self.dev_status.config(
                    text="Click a device to play there. Playing on this computer streams embedded audio.")
            self.root.after(0, fill)
        threading.Thread(target=work, daemon=True).start()

    def _dev_select(self):
        sel = self.dev_list.curselection()
        if not sel or not getattr(self, "_devices", None) or sel[0] >= len(self._devices):
            return
        dev = self._devices[sel[0]]
        if hasattr(self.engine, "select_device"):
            def work():
                try:
                    self.engine.select_device(dev)
                    self._toast(f"Now playing on: {dev.get('name')}")
                except Exception as e:
                    self._toast(str(e))
            threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------- lyrics
    def _refresh_lyrics(self):
        t = self.snap.track
        if not t:
            return
        def work():
            try:
                data = self.engine.lyrics_for(t)
            except Exception:
                data = None
            def fill():
                if data and data.get("lines"):
                    self.lyr.config(state="normal")
                    self.lyr.delete("1.0", "end")
                    self.lyr.insert("1.0", "\n".join(data["lines"]))
                    self.lyr.config(state="disabled")
            self.root.after(0, fill)
        threading.Thread(target=work, daemon=True).start()

    # --------------------------------------------------------------- poll
    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                self.snap = self.engine.snapshot()
                self._update()
            except Exception:
                pass
            self._stop.wait(0.5)

    def _changed(self, key, value):
        if self._last.get(key) == value:
            return False
        self._last[key] = value
        return True

    def _sync_queue_now(self):
        q = self.snap.queue or []
        key = (len(q), q[0].uri if q else None, q[-1].uri if q else None)
        if key != self._queue_key:
            self._queue_key = key
            self.queue_list.set_items(q, self.images)

    def _update(self):
        snap = self.snap
        t = snap.track
        try:
            if t:
                if self._changed("name", t.name):
                    self.title.config(text=t.name)
                    self.m_title.config(text=t.name)
                if self._changed("artists", t.artists):
                    self.artist.config(text=t.artists)
                    self.m_artist.config(text=t.artists)
                if self._changed("album", t.album):
                    self.album.config(text=t.album)
                if self._changed("playing", snap.playing):
                    self.play_btn.config(text="❚❚" if snap.playing else "▶")
                if self._changed("time", f"{snap.position_ms}/{snap.duration_ms}"):
                    pos, dur = int(snap.position_ms or 0), int(snap.duration_ms or 0)
                    self.time.config(text=f"{_fmt(pos)} / {_fmt(dur)}")
                    self.progress.delete("all")
                    w = max(1, self.progress.winfo_width())
                    pct = pos / dur if dur else 0
                    self.progress.create_rectangle(0, 0, int(w * pct), 6,
                                                   fill=ui.ACCENT, outline="")
                if self._changed("art", t.image_url):
                    self.images.attach(self.art, t.image_url, 96)
                    self.images.attach(self.mini_art, t.image_url, 52)
                    self.images.attach_background(self.home_bd, t.image_url,
                                                  self.home_bd.winfo_width() or 800,
                                                  170)
                if self._changed("liked", bool(t.liked)):
                    self.like_btn.config(text="♥" if t.liked else "♡",
                                         fg=ui.GREEN if t.liked else ui.MUTED)
            else:
                if self._changed("name", ""):
                    self.title.config(text="Nothing playing")
                    self.m_title.config(text="Nothing playing")
                    self.artist.config(text="")
                    self.m_artist.config(text="")
                    self.play_btn.config(text="▶")

            if self._changed("shuffle", snap.shuffle):
                self.shuf_btn.config(fg=ui.ACCENT if snap.shuffle else ui.MUTED)
            if self._changed("repeat", snap.repeat):
                self.rep_btn.config(fg=ui.ACCENT if snap.repeat != "off" else ui.MUTED)
            if self._current_tab == "Home":
                self.home_top_tracks.set_current(t.uri if t else None)
            elif self._current_tab == "Queue":
                self._sync_queue_now()
        except Exception:
            pass

    def _toast(self, msg):
        try:
            self.root.title(f"Permify — {msg}")
        except Exception:
            pass

    # ------------------------------------------------------------------ run
    def run(self):
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


def _num(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return "0"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def run(engine, cfg: dict, demo: bool = False):
    PermifyGUI(engine, cfg, demo=demo).run()
