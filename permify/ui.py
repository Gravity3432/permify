"""Reusable high-performance UI widgets for Permify.

- ImageCache: async, cached album/cover art loading with an automatic
  gradient fallback (so demo/offline content still looks great).
- ScrollFrame: a lightweight scrollable canvas container.
- TrackList: virtual-scrolled rich track rows (cover, title, clickable
  artist, album, duration, heart).
- TileGrid: a reflowing grid of cover tiles (playlists / albums / artists).

Kept deliberately lean so the app stays performance-light.
Made with heart by @johnthemailboy.
"""
from __future__ import annotations

import threading
import tkinter as tk

try:
    from PIL import Image, ImageTk, ImageEnhance
    _HAS_PIL = True
except Exception:  # pragma: no cover
    _HAS_PIL = False

# --- palette (Permify vibe) ---------------------------------------------
BG = "#0f1115"
SIDE = "#171a21"
PANEL = "#1f232c"
PANEL2 = "#232836"
TEXT = "#e8e8ea"
MUTED = "#8a90a0"
ACCENT = "#7c5cff"
ACCENT_DIM = "#5b43c0"
ACCENT_TEXT = "#ffffff"
GREEN = "#1db954"
LINE = "#262a33"
ROW_HOVER = "#22262f"
FONT = "Segoe UI"

MAX_ROWS = 500  # cap per list so huge libraries stay light


# ------------------------------------------------------------------ images
def _gradient_image(seed: str, w: int = 300, h: int = 300):
    """Deterministic pastel gradient tile (used when no cover URL exists)."""
    import colorsys
    hsh = abs(hash(seed)) % 360
    hue = hsh / 360.0
    top = colorsys.hsv_to_rgb(hue, 0.45, 0.62)
    bot = colorsys.hsv_to_rgb((hue + 0.12) % 1.0, 0.55, 0.32)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        f = y / max(1, h - 1)
        r = int(top[0] + (bot[0] - top[0]) * f)
        g = int(top[1] + (bot[1] - top[1]) * f)
        b = int(top[2] + (bot[2] - top[2]) * f)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


class ImageCache:
    """Loads images once, caches PhotoImages, falls back to a gradient."""

    def __init__(self):
        self._photos = {}       # key -> PhotoImage
        self._pending = {}      # key -> list of (widget, 'photo'|'bg')
        self._loading = set()
        self._fallback = {}
        self._refs = []

    def get(self, key: str, size: int) -> "tk.PhotoImage | None":
        return self._photos.get((key, size))

    def _load(self, key: str, url, size: int):
        if key in self._loading:
            return
        self._loading.add(key)
        def work():
            try:
                img = self._fetch(url, size)
                photo = ImageTk.PhotoImage(img)
                self._photos[(key, size)] = photo
                self._refs.append(photo)
                self.root.after(0, lambda: self._notify(key, size))
            except Exception:
                pass
            finally:
                self._loading.discard(key)
        threading.Thread(target=work, daemon=True).start()

    def _fetch(self, url, size: int):
        import io
        import requests
        r = requests.get(url, timeout=8)
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img = img.resize((size, size), Image.LANCZOS)
        return img

    def _notify(self, key, size):
        for widget, kind in list(self._pending.pop((key, size), [])):
            try:
                widget._apply_photo(self.get(key, size))
            except Exception:
                pass

    def attach(self, widget, url: str, size: int):
        """Point a widget at a URL; it gets an async image or a gradient."""
        widget._image_cache = self
        if url and url.startswith("http"):
            photo = self.get(url, size)
            if photo is not None:
                widget._apply_photo(photo)
                return
            self._pending.setdefault((url, size), []).append((widget, "photo"))
            self._load(url, url, size)
        else:
            widget._apply_photo(self._gradient(url or widget._seed, size))

    def _gradient(self, seed: str, size: int):
        key = ("grad", seed, size)
        if key not in self._fallback:
            self._fallback[key] = ImageTk.PhotoImage(_gradient_image(seed, size, size))
            self._refs.append(self._fallback[key])
        return self._fallback[key]

    def attach_background(self, widget, url: str, w: int, h: int):
        """Blurred, darkened backdrop from an album cover (or gradient)."""
        widget._image_cache = self
        if url and url.startswith("http"):
            def done():
                try:
                    widget._apply_bg(self._blur(url, w, h))
                except Exception:
                    pass
            self._load_bg(url, w, h, done)
        else:
            widget._apply_bg(self._gradient(widget._seed, max(w, h)))

    def _load_bg(self, url, w, h, done):
        if ("bg", url) in self._photos:
            return
        if url in self._loading:
            return
        self._loading.add(url)
        def work():
            try:
                self._photos[("bg", url)] = self._blur(url, w, h)
                self._refs.append(self._photos[("bg", url)])
                self.root.after(0, done)
            except Exception:
                pass
            finally:
                self._loading.discard(url)
        threading.Thread(target=work, daemon=True).start()

    def _blur(self, url, w, h):
        import io
        import requests
        r = requests.get(url, timeout=8)
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        small = img.resize((16, 16), Image.BILINEAR)
        blurred = small.resize((w, h), Image.BILINEAR)
        return ImageEnhance.Brightness(blurred).enhance(0.5)


class _ImageView(tk.Canvas):
    """A square image that fills itself; draws a rounded cover or gradient."""
    def __init__(self, master, size, seed="", corner=8, bg=SIDE):
        super().__init__(master, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0)
        self._size = size
        self._seed = seed or "cover"
        self._photo = None
        self._corner = corner
        self._bg = bg
        self.bind("<Configure>", lambda e: self._redraw())

    def _apply_photo(self, photo):
        self._photo = photo
        self._redraw()

    def _apply_bg(self, photo):
        self.delete("all")
        self.create_image(self._size // 2, self._size // 2, image=photo)

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 2:
            return
        if self._photo is not None:
            self.create_image(w // 2, w // 2, image=self._photo)


class Backdrop(tk.Canvas):
    """Full-size blurred album-art backdrop for the now-playing area."""
    def __init__(self, master, bg=BG):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0)
        self._photo = None
        self._seed = "bg"
        self.bind("<Configure>", lambda e: self._redraw())

    def _apply_bg(self, photo):
        self._photo = photo
        self._redraw()

    def _apply_photo(self, photo):
        self._photo = photo
        self._redraw()

    def _redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2 or self._photo is None:
            return
        self.create_image(w // 2, h // 2, image=self._photo)


class ScrollFrame(tk.Frame):
    """A scrollable body that fills available space."""

    def __init__(self, master, bg=BG):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        sb = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                          bg=bg, troughcolor=bg, activebackground=ACCENT,
                          highlightthickness=0, width=8)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>",
                       lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self._sync_width())
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.body.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all_hold = None

    def _sync_width(self):
        self.canvas.itemconfigure(self._win, width=self.canvas.winfo_width())

    def _on_wheel(self, e):
        try:
            self.canvas.yview_scroll(int(-e.delta / 120), "units")
        except Exception:
            pass

    def clear(self):
        for w in self.body.winfo_children():
            w.destroy()


# ------------------------------------------------------------------ rows
class TrackRow(tk.Frame):
    def __init__(self, master, track, cache, on_play=None, on_artist=None,
                 on_like=None, show_liked=True, palette=None, playing=False):
        super().__init__(master, bg=ROW_HOVER if playing else BG)
        self.track = track
        self._cache = cache
        self._size = 44
        self.grid_columnconfigure(2, weight=1)

        self.thumb = _ImageView(self, self._size, seed=track.name or "t")
        self.thumb.grid(row=0, column=0, rowspan=2, padx=(6, 10), pady=5)
        cache.attach(self.thumb, track.image_url, self._size)

        self.name_lbl = tk.Label(self, text=track.name or "", bg=self["bg"],
                                 fg=TEXT, font=(FONT, 12), anchor="w")
        self.name_lbl.grid(row=0, column=1, sticky="w")

        artist = track.artists or "?"
        self.sub_lbl = tk.Label(self, text=f"{artist} · {track.album or ''}",
                                bg=self["bg"], fg=MUTED, font=(FONT, 10), anchor="w")
        self.sub_lbl.grid(row=1, column=1, sticky="w")
        if on_artist and track.artist_uris:
            self.sub_lbl.bind("<Button-1>",
                              lambda e: on_artist(self.track))

        self.dur_lbl = tk.Label(self, text=track.duration_text, bg=self["bg"],
                                fg=MUTED, font=(FONT, 10))
        self.dur_lbl.grid(row=0, column=3, rowspan=2, sticky="e", padx=10)
        if on_like:
            self.heart = tk.Label(self, text="♥" if track.liked else "♡",
                                  bg=self["bg"],
                                  fg=GREEN if track.liked else MUTED,
                                  font=(FONT, 13), cursor="hand2")
            self.heart.grid(row=0, column=4, rowspan=2, sticky="e", padx=(0, 12))
            self.heart.bind("<Button-1>", lambda e: on_like(self.track))

        self._bg = self["bg"]
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        for w in [self.name_lbl, self.sub_lbl, self.dur_lbl]:
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
        if on_play:
            for w in [self, self.name_lbl, self.sub_lbl, self.dur_lbl, self.thumb]:
                w.bind("<Button-1>", lambda e: on_play(self.track))

    def _on_enter(self, e):
        if self._bg == ROW_HOVER:
            return
        self.configure(bg=ROW_HOVER)
        for w in self.winfo_children():
            try:
                w.configure(bg=ROW_HOVER)
            except Exception:
                pass

    def _on_leave(self, e):
        self.configure(bg=BG)
        for w in self.winfo_children():
            try:
                w.configure(bg=BG)
            except Exception:
                pass


class TrackList(ScrollFrame):
    """Scrollable rich list of tracks."""

    def __init__(self, master, bg=BG):
        super().__init__(master, bg=bg)
        self._rows = []
        self.on_play = None
        self.on_artist = None
        self.on_like = None
        self.current_uri = None

    def set_current(self, uri):
        self.current_uri = uri
        for row in self._rows:
            want = row.track.uri == uri
            if row._bg != (ROW_HOVER if want else BG):
                row.configure(bg=ROW_HOVER if want else BG)
                for w in row.winfo_children():
                    try:
                        w.configure(bg=ROW_HOVER if want else BG)
                    except Exception:
                        pass

    def set_items(self, tracks, cache):
        self.clear()
        self._rows = []
        for t in tracks[:MAX_ROWS]:
            r = TrackRow(self.body, t, cache, self.on_play, self.on_artist,
                         self.on_like, playing=(t.uri == self.current_uri))
            r.pack(fill="x")
            self._rows.append(r)


# ------------------------------------------------------------------ tiles
class Tile(tk.Frame):
    def __init__(self, master, cache, label, url="", seed="", size=130,
                 command=None, sub=""):
        super().__init__(master, bg=BG)
        self.grid_columnconfigure(0, weight=1)
        self.im = _ImageView(self, size, seed=seed or label, bg=BG)
        self.im.grid(row=0, column=0, pady=(0, 6))
        cache.attach(self.im, url, size)
        if command:
            self.im.bind("<Button-1>", lambda e: command())
        self.nm = tk.Label(self, text=label, bg=BG, fg=TEXT, font=(FONT, 11),
                           anchor="w", wraplength=size)
        self.nm.grid(row=1, column=0, sticky="w")
        if sub:
            tk.Label(self, text=sub, bg=BG, fg=MUTED, font=(FONT, 9),
                     anchor="w").grid(row=2, column=0, sticky="w")


class TileGrid(ScrollFrame):
    """Reflowing grid of cover tiles."""

    def __init__(self, master, bg=BG, cols=4, tile_size=130):
        super().__init__(master, bg=bg)
        self._cols = cols
        self._tile_size = tile_size
        self._tiles = []
        self.body.grid_columnconfigure(tuple(range(cols)), weight=1)

    def set_items(self, items, cache):
        """items: list of dicts {label, url, sub, seed, command}."""
        self.clear()
        self._tiles = []
        cols = self._cols
        for i, it in enumerate(items):
            t = Tile(self.body, cache, it.get("label", ""), it.get("url", ""),
                     it.get("seed", ""), self._tile_size,
                     it.get("command"), it.get("sub", ""))
            t.grid(row=i // cols, column=i % cols, padx=8, pady=8, sticky="nsew")
            self._tiles.append(t)
