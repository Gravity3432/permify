"""Offline demo engine for Permify — fake music, no account, no audio.
Lets you try the GUI before connecting to Spotify.
"""
from __future__ import annotations

import time
from typing import Callable, List

from .models import Playlist, Snapshot, Track

CATALOG = [
    ("p01", "Neon Horizon", "Subwave", "Midnight City Drive", 224_000),
    ("p02", "Sunset Circuit", "Analog Dreams", "Golden Hour", 218_000),
    ("p03", "Digital Ocean", "Wave Rider", "Blue Code", 241_000),
    ("p04", "Glass Petals", "Violet Sky", "Soft Machines", 197_000),
    ("p05", "Chrome Hearts", "Neon District", "Synthwave City", 233_000),
    ("p06", "Aurora Fields", "Night Bloom", "Electric Garden", 256_000),
    ("p07", "Gravity Well", "Deep Orbit", "Celestial", 245_000),
]

BY_ID = {
    i: Track(id=i, uri=f"spotify:track:{i}", name=n, artists=a, album=b,
             duration_ms=d) for i, n, a, b, d in CATALOG
}


class DemoEngine:
    mode = "demo"

    def __init__(self, cfg=None):
        self._tracks = [BY_ID[i] for i in BY_ID]
        self._order = list(range(len(self._tracks)))
        self._pos = 0
        self._playing = True
        self._start = time.monotonic()
        self._vol = 60
        self.shuffle = False
        self.repeat = "off"
        self.context_name = "Demo Mix"
        self._toast_cb: Callable[[str], None] = lambda m: None

    # -- basic API the GUI needs ---------------------------------------
    def start(self, toast: Callable[[str], None]):
        self._toast_cb = toast

    def me_name(self) -> str:
        return "demo listener"

    @property
    def device_label(self) -> str:
        return "demo (no audio)"

    def get_playlists(self) -> List[Playlist]:
        return [
            Playlist(id="demo_pl", uri="spotify:playlist:demo",
                     name="Demo Mix", owner="permify", count=len(self._tracks)),
        ]

    def get_playlist_tracks(self, pl: Playlist) -> List[Track]:
        return self._tracks

    def get_liked(self) -> List[Track]:
        return self._tracks[:4]

    def search(self, q: str) -> List[Track]:
        q = q.lower()
        return [t for t in self._tracks
                if q in t.name.lower() or q in t.artists.lower()]

    def play_tracks(self, tracks: List[Track], index: int, context: str) -> None:
        self._tracks = list(tracks)
        self._order = [index] + [i for i in range(len(tracks)) if i != index]
        self._pos = 0
        self.context_name = context or "Permify Mix"
        self._playing = True
        self._start = time.monotonic()

    def play_playlist(self, pl: Playlist) -> None:
        self.play_tracks(self.get_playlist_tracks(pl), 0, pl.name)

    def toggle(self) -> None:
        self._playing = not self._playing
        self._start = time.monotonic()

    def next(self) -> None:
        self._pos = (self._pos + 1) % len(self._order)
        self._playing = True
        self._start = time.monotonic()

    def prev(self) -> None:
        self._pos = (self._pos - 1) % len(self._order)
        self._playing = True
        self._start = time.monotonic()

    def seek_ms(self, ms: int) -> None:
        self._seek_ms = int(ms)
        self._start = time.monotonic()

    def seek_step(self, delta: int) -> None:
        cur = self.position_ms()
        self.seek_ms(cur + delta)

    def set_volume(self, v: int) -> None:
        self._vol = max(0, min(100, int(v)))

    def volume_step(self, delta: int) -> None:
        self.set_volume(self._vol + delta)

    def shuffle_toggle(self) -> bool:
        self.shuffle = not self.shuffle
        return self.shuffle

    def repeat_cycle(self) -> str:
        self.repeat = {"off": "context", "context": "track",
                       "track": "off"}[self.repeat]
        return self.repeat

    def position_ms(self) -> int:
        if not self._playing:
            return getattr(self, "_seek_ms", 0)
        return int(time.monotonic() - self._start) * 1000

    def snapshot(self) -> Snapshot:
        tr = self._tracks[self._order[self._pos]]
        pos = self.position_ms()
        if pos >= tr.duration_ms and self.repeat == "track":
            pos = 0
        elif pos >= tr.duration_ms:
            # auto-advance
            self.next()
            tr = self._tracks[self._order[self._pos]]
            pos = 0
        upcoming = [self._tracks[self._order[(self._pos + 1 + i) % len(self._order)]]
                    for i in range(min(10, len(self._order) - 1))]
        return Snapshot(
            track=tr, playing=self._playing, position_ms=pos,
            volume=self._vol, shuffle=self.shuffle, repeat=self.repeat,
            context_name=self.context_name, queue=upcoming,
            status="playing" if self._playing else "paused",
            device_label=self.device_label,
        )

    def shutdown(self) -> None:
        pass
