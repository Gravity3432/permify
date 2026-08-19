"""Reusable high-performance UI widgets for Permify.

Design for speed: lists and tile grids are drawn on a single tk.Canvas as
lightweight items (text / images / rects) and VIRTUALIZED — only the rows
that are on screen are drawn, and they're redrawn on scroll. This avoids
creating thousands of tkinter widget objects (the #1 cause of lag in a
widget-per-row layout).

ImageCache loads album art on worker threads, creates PhotoImages on the
main thread, and falls back to fast colored placeholders.

Made with heart by @johnthemailboy.
"""
from __future__ import annotations

import threading
import tkinter as tk

try:
    from PIL import Image, ImageTk
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
ROW_HOVER = "#242a36"
FONT = "Segoe UI"

MAX_ROWS = 400  # cap per list/grid so huge libraries stay light


# ------------------------------------------------------------------ images
def _accent_color(seed: str, base=120):
    """Stable pastel accent color for placeholder tiles."""
    h = abs(hash(seed)) % 360
    s, v = 0.55, 0.55
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h / 360.0, s, v)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


class ImageCache:
    """Caches PhotoImages; downloads on workers, wraps on the main thread."""

    _MAX_DOWNLOADS = 6

    def __init__(self):
        self._photos = {}
        self._subscribers = {}
        self._loading = set()
        self._refs = []
        self._sem = threading.BoundedSemaphore(ImageCache._MAX_DOWNLOADS)

    def get(self, url: str, size: int):
        return self._photos.get((url, size))

    def attach(self, widget, url: str, size: int):
        """Ensure an image is loaded; call widget._apply_photo when ready."""
        widget._image_cache = self
        if not url or not url.startswith("http"):
            return
        key = (url, size)
        if key in self._photos:
            widget._apply_photo(self._photos[key])
            return
        self._subscribers.setdefault(key, set()).add(widget)
        if url not in self._loading:
            self._loading.add(url)
            threading.Thread(target=self._fetch, args=(url, size),
                             daemon=True).start()

    def _fetch(self, url, size):
        try:
            with self._sem:
                img = self._download(url, size)
            key = (url, size)
            self._photos[key] = ImageTk.PhotoImage(img)
            self._refs.append(self._photos[key])
            self.root.after(0, lambda: self._notify(url, size))
        except Exception:
            pass
        finally:
            self._loading.discard(url)

    def _notify(self, url, size):
        key = (url, size)
        subs = self._subscribers.pop(key, set())
        photo = self._photos.get(key)
        for w in subs:
            try:
                w._apply_photo(photo)
            except Exception:
                pass

    def _download(self, url, size):
        import io
        import requests
        r = requests.get(url, timeout=10)
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        return img.resize((size, size), Image.LANCZOS)

    def art_photo(self, url, size):
        """PhotoImage for a big cover/avatar (loaded async, applied via cb)."""
        return self.get(url, size)


def _truncate(text: str, max_chars: int) -> str:
    text = text or ""
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


class TrackList(tk.Canvas):
    """Virtualized, canvas-drawn list of track rows (fast scrolling)."""

    ROW_H = 54
    THUMB = 44

    def __init__(self, master, bg=BG, height=None):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0)
        if height:
            self.configure(height=height)
        self.configure(yscrollincrement=self.ROW_H)
        self._rows = []
        self._cache = None
        self._current = None
        self._hover = -1
        self._requested = set()
        self.on_play = None
        self.on_artist = None
        self.on_like = None

        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: (setattr(self, "_hover", -1), self._redraw())[1])
        self.bind("<Button-1>", self._click)

        self.tag_bind("play", "<Button-1>", self._click_play)
        self.tag_bind("artist", "<Button-1>", self._click_artist)
        self.tag_bind("heart", "<Button-1>", self._click_heart)

    def _apply_photo(self, photo=None):
        self._redraw()

    # public API ---------------------------------------------------------
    def set_current(self, uri):
        self._current = uri
        self._redraw()

    def set_items(self, tracks, cache):
        self._rows = list(tracks)[:MAX_ROWS]
        self._cache = cache
        self._requested = set()
        h = max(1, len(self._rows)) * self.ROW_H
        self.configure(scrollregion=(0, 0, 1, h))
        self._redraw()

    def clear(self):
        self.set_items([], self._cache)

    # events -------------------------------------------------------------
    def _wheel(self, e):
        try:
            self.yview_scroll(int(-e.delta / 120), "units")
            self._redraw()
        except Exception:
            pass

    def _row_at(self, y):
        top = self.canvasy(0)
        return int((top + y) // self.ROW_H)

    def _motion(self, e):
        r = self._row_at(e.y)
        if 0 <= r < len(self._rows) and r != self._hover:
            self._hover = r
            self._redraw()
        elif not (0 <= r < len(self._rows)) and self._hover != -1:
            self._hover = -1
            self._redraw()

    def _click(self, e):
        pass  # handled by tag bindings

    def _click_play(self, e):
        r = self._row_at(e.y)
        if 0 <= r < len(self._rows) and self.on_play:
            self.on_play(self._rows[r])

    def _click_artist(self, e):
        r = self._row_at(e.y)
        if 0 <= r < len(self._rows) and self.on_artist and self._rows[r].artist_uris:
            self.on_artist(self._rows[r])

    def _click_heart(self, e):
        r = self._row_at(e.y)
        if 0 <= r < len(self._rows) and self.on_like:
            self.on_like(self._rows[r])

    # drawing ------------------------------------------------------------
    def _photo(self, track):
        url = track.image_url
        if url and url.startswith("http"):
            p = self._cache.get(url, self.THUMB) if self._cache else None
            if p is not None:
                return p
            if url not in self._requested and self._cache:
                self._requested.add(url)
                self._cache.attach(self, url, self.THUMB)
            return None
        return None

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 2 or not self._rows:
            return
        top = self.canvasy(0)
        hh = self.winfo_height()
        first = max(0, int(top // self.ROW_H))
        last = min(len(self._rows), int((top + hh) // self.ROW_H) + 1)
        for i in range(first, last):
            self._draw_row(i, i * self.ROW_H - top)

    def _draw_row(self, i, cy):
        t = self._rows[i]
        w = self.winfo_width()
        selected = t.uri == self._current
        hover = i == self._hover
        fill = ROW_HOVER if (hover or selected) else BG
        play_tag = "play"
        self.create_rectangle(0, cy, w, cy + self.ROW_H, fill=fill,
                              outline="", tags=play_tag)

        x0 = 8
        y0 = cy + (self.ROW_H - self.THUMB) // 2
        ph = self._photo(t)
        if ph is not None:
            self.create_image(x0 + self.THUMB // 2, y0 + self.THUMB // 2,
                              image=ph, tags=play_tag)
        else:
            c = _accent_color(t.name or "t")
            self.create_rectangle(x0, y0, x0 + self.THUMB, y0 + self.THUMB,
                                  fill=c, outline="", tags=play_tag)
            self.create_text(x0 + self.THUMB // 2, y0 + self.THUMB // 2,
                             text="♪", fill="#0b0d11", font=(FONT, 18),
                             tags=play_tag)

        tx = x0 + self.THUMB + 12
        maxchars = max(8, int((w - tx - 150) / 7))
        title = _truncate(t.name, maxchars)
        self.create_text(tx, cy + 20, text=title, anchor="w", fill=TEXT,
                         font=(FONT, 12, "bold"), tags=play_tag)
        # artist (clickable) + album
        if t.artist_uris:
            aid = self.create_text(tx, cy + 38, text=t.artists or "", anchor="w",
                                   fill=ACCENT, font=(FONT, 10, "underline"),
                                   tags="artist")
        else:
            aid = self.create_text(tx, cy + 38, text=t.artists or "", anchor="w",
                                   fill=MUTED, font=(FONT, 10), tags=play_tag)
        try:
            bb = self.bbox(aid)
            ax = (bb[2] + 8) if bb else tx + 90
        except Exception:
            ax = tx + 90
        self.create_text(ax, cy + 38, text="· " + _truncate(t.album, maxchars),
                         anchor="w", fill=MUTED, font=(FONT, 10), tags=play_tag)

        self.create_text(w - 54, cy + 26, text=t.duration_text, anchor="e",
                         fill=MUTED, font=(FONT, 10))
        heart = "♥" if t.liked else "♡"
        self.create_text(w - 26, cy + 27, text=heart,
                         fill=GREEN if t.liked else MUTED, font=(FONT, 14),
                         tags="heart")


class TileGrid(tk.Canvas):
    """Virtualized, canvas-drawn grid of cover tiles (fast scrolling)."""

    def __init__(self, master, bg=BG, cols=5, tile_size=118, height=None, pad=8):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0)
        if height:
            self.configure(height=height)
        self._items = []
        self._cache = None
        self._cols = cols
        self._tile = tile_size
        self._pad = pad
        self._requested = set()
        self._hover = -1
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-1>", self._click)
        self.tag_bind("tile", "<Button-1>", self._click_tile)

    def _apply_photo(self, photo=None):
        self._redraw()

    def set_items(self, items, cache):
        self._items = list(items)[:MAX_ROWS]
        self._cache = cache
        self._requested = set()
        self._redraw()

    def clear(self):
        self.set_items([], self._cache)

    def _cols_here(self):
        w = self.winfo_width()
        step = self._tile + self._pad
        return max(1, (w + self._pad) // step)

    def _rows_total(self):
        cols = self._cols_here()
        return max(1, -(-len(self._items) // cols))

    def _wheel(self, e):
        try:
            self.yview_scroll(int(-e.delta / 120), "units")
            self._redraw()
        except Exception:
            pass

    def _click(self, e):
        pass

    def _click_tile(self, e):
        cols = self._cols_here()
        top = self.canvasy(0)
        row = int((top + e.y) // (self._tile + self._pad))
        col = int(e.x // (self._tile + self._pad))
        idx = row * cols + col
        if 0 <= idx < len(self._items):
            cmd = self._items[idx].get("command")
            if cmd:
                cmd()

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 2 or not self._items:
            return
        cols = self._cols_here()
        step = self._tile + self._pad
        rows = self._rows_total()
        h = rows * step + self._pad
        self.configure(scrollregion=(0, 0, 1, h))
        top = self.canvasy(0)
        hh = self.winfo_height()
        first = max(0, int(top // step))
        last = min(rows, int((top + hh) // step) + 1)
        for r in range(first, last):
            for c in range(cols):
                idx = r * cols + c
                if idx >= len(self._items):
                    break
                self._draw_tile(idx, r, c, r * step - top)

    def _photo(self, item):
        url = item.get("url")
        if url and url.startswith("http"):
            p = self._cache.get(url, self._tile) if self._cache else None
            if p is not None:
                return p
            if url not in self._requested and self._cache:
                self._requested.add(url)
                self._cache.attach(self, url, self._tile)
            return None
        return None

    def _draw_tile(self, idx, r, c, cy):
        item = self._items[idx]
        x0 = c * (self._tile + self._pad) + self._pad
        ph = self._photo(item)
        if ph is not None:
            self.create_image(x0 + self._tile // 2, cy + self._tile // 2,
                              image=ph, tags="tile")
        else:
            col = _accent_color(item.get("seed") or item.get("label") or "t")
            self.create_rectangle(x0, cy, x0 + self._tile, cy + self._tile,
                                  fill=col, outline="", tags="tile")
            self.create_text(x0 + self._tile // 2, cy + self._tile // 2,
                             text="♪", fill="#0b0d11", font=(FONT, 30),
                             tags="tile")
        label = _truncate(item.get("label", ""), int(self._tile / 7))
        self.create_text(x0 + 2, cy + self._tile + 16, text=label, anchor="w",
                         fill=TEXT, font=(FONT, 10, "bold"), tags="tile")
        sub = item.get("sub")
        if sub:
            self.create_text(x0 + 2, cy + self._tile + 32, text=_truncate(sub, int(self._tile / 7)),
                             anchor="w", fill=MUTED, font=(FONT, 9))


class _ImageView(tk.Canvas):
    """A square image widget (used for big art / avatars)."""
    def __init__(self, master, size, seed="", bg=SIDE, corner=10):
        super().__init__(master, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0)
        self._size = size
        self._seed = seed or "cover"
        self._photo = None
        self._bg = bg

    def _apply_photo(self, photo):
        self._photo = photo
        self._redraw()

    def _redraw(self):
        self.delete("all")
        s = self.winfo_width()
        if s < 2 or self._photo is None:
            return
        self.create_image(s // 2, s // 2, image=self._photo)


class Backdrop(tk.Canvas):
    """Optional blurred album-art backdrop."""
    def __init__(self, master, bg=BG):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0)
        self._photo = None
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
