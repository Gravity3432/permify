"""Offline demo engine for Permify — fake music, no account, no audio.

Lets you try the GUI before connecting to Spotify. Everything the real
engine does, it fakes with in-memory data so every tab is previewable.
"""
from __future__ import annotations

import time
from typing import Callable, List

from .models import Album, Artist, Playlist, Snapshot, Track

ARTISTS = [
    ("a01", "Subwave", 1_204_000),
    ("a02", "Analog Dreams", 342_000),
    ("a03", "Wave Rider", 918_000),
    ("a04", "Violet Sky", 155_000),
    ("a05", "Neon District", 2_113_000),
    ("a06", "Night Bloom", 87_000),
    ("a07", "Deep Orbit", 640_000),
]
ALBUMS = {
    "al01": ("Midnight City Drive", "a01"),
    "al02": ("Golden Hour", "a02"),
    "al03": ("Blue Code", "a03"),
    "al04": ("Soft Machines", "a04"),
    "al05": ("Synthwave City", "a05"),
    "al06": ("Electric Garden", "a06"),
    "al07": ("Celestial", "a07"),
}
CATALOG = [
    ("p01", "Neon Horizon", "a01", "al01", 224_000),
    ("p02", "Sunset Circuit", "a02", "al02", 218_000),
    ("p03", "Digital Ocean", "a03", "al03", 241_000),
    ("p04", "Glass Petals", "a04", "al04", 197_000),
    ("p05", "Chrome Hearts", "a05", "al05", 233_000),
    ("p06", "Aurora Fields", "a06", "al06", 256_000),
    ("p07", "Gravity Well", "a07", "al07", 245_000),
]
_LYRICS = [
    "under the neon horizon", "we chase the fading light",
    "midnight city calls to me", "in a world of black and white",
    "ride the waves of digital dreams", "where the static softly screams",
]


def _t(id, name, artist_id, album_id, dur):
    aname = dict((a[0], a[1]) for a in ARTISTS)[artist_id]
    alname = ALBUMS[album_id][0]
    return Track(
        id=id, uri=f"spotify:track:{id}", name=name, artists=aname,
        album=alname, duration_ms=dur,
        artist_uris=[f"spotify:artist:{artist_id}"],
        artist_ids=[artist_id],
        album_uri=f"spotify:album:{album_id}",
    )


BY_ID = {i: _t(i, n, a, al, d) for i, n, a, al, d in CATALOG}
BY_ARTIST = {a[0]: Artist(id=a[0], uri=f"spotify:artist:{a[0]}", name=a[1],
                          followers=a[2]) for a in ARTISTS}
BY_ALBUM = {k: Album(id=k, uri=f"spotify:album:{k}", name=v[0], artists=v[0],
                     year="2024") for k, v in ALBUMS.items()}


class DemoEngine:
    mode = "demo"

    def __init__(self, cfg=None):
        self._tracks = [BY_ID[i] for i in BY_ID]
        self._order = list(range(len(self._tracks)))
        self._pos = 0
        self._playing = True
        self._start = time.monotonic()
        self._vol = 60
        self._liked = {"p01", "p04"}
        self._following = set()
        self.shuffle = False
        self.repeat = "off"
        self.context_name = "Demo Mix"
        self._toast_cb: Callable[[str], None] = lambda m: None

    def start(self, toast: Callable[[str], None]):
        self._toast_cb = toast

    def me_name(self) -> str:
        return "demo listener"

    @property
    def device_label(self) -> str:
        return "Demo (this computer)"

    # -- library ---------------------------------------------------------
    def get_playlists(self) -> List[Playlist]:
        return [
            Playlist(id="demo_pl", uri="spotify:playlist:demo",
                     name="Demo Mix", owner="permify", count=len(self._tracks)),
            Playlist(id="pl2", uri="spotify:playlist:2", name="Late Night Drive",
                     owner="permify", count=5),
            Playlist(id="pl3", uri="spotify:playlist:3", name="Focus Flow",
                     owner="permify", count=4),
        ]

    def get_playlist_tracks(self, pl: Playlist) -> List[Track]:
        return self._tracks

    def get_liked(self) -> List[Track]:
        return [self._tracks[i] for i, t in enumerate(self._tracks)
                if t.id in self._liked] or self._tracks[:4]

    def search(self, q: str) -> List[Track]:
        q = q.lower()
        return [t for t in self._tracks
                if q in t.name.lower() or q in t.artists.lower()]

    def search_all(self, q: str) -> dict:
        q = q.lower()
        return {
            "tracks": [t for t in self._tracks if q in t.name.lower()],
            "artists": [a for a in BY_ARTIST.values() if q in a.name.lower()],
            "albums": [a for a in BY_ALBUM.values() if q in a.name.lower()],
            "playlists": self.get_playlists(),
        }

    def top_tracks(self) -> List[Track]:
        return self._tracks[:5]

    def top_artists(self) -> List[Artist]:
        return list(BY_ARTIST.values())[:6]

    def recently_played(self) -> List[Track]:
        return list(reversed(self._tracks[-4:]))

    def artist_albums(self, artist) -> List[Album]:
        aid = getattr(artist, "id", None) or str(artist)
        return [BY_ALBUM[k] for k, v in ALBUMS.items() if v[1] == aid]

    def artist_top(self, artist) -> List[Track]:
        name = (getattr(artist, "name", "") or "").lower()
        hit = [t for t in self._tracks if t.artists.lower() == name]
        return hit or self._tracks[:5]

    def album_tracks(self, album_id, album_meta=None) -> List[Track]:
        uri = getattr(album_meta, "uri", None) or getattr(album_meta, "id", None)
        aname = (getattr(album_meta, "name", "") or "").lower()
        hit = [t for t in self._tracks
               if (uri and t.album_uri == f"spotify:album:{album_id}")
               or (aname and t.album.lower() == aname)]
        return hit or self._tracks[:5]

    def artist_info(self, artist) -> Artist:
        aid = getattr(artist, "id", None) or str(artist)
        return BY_ARTIST.get(aid, Artist("", "", str(artist)))

    def follow_artist(self, artist, flag: bool) -> bool:
        aid = getattr(artist, "id", None) or str(artist)
        if flag:
            self._following.add(aid)
        else:
            self._following.discard(aid)
        return True

    def is_following_artist(self, artist) -> bool:
        aid = getattr(artist, "id", None) or str(artist)
        return aid in self._following

    def set_liked(self, track: Track, flag: bool) -> bool:
        if flag:
            self._liked.add(track.id)
        else:
            self._liked.discard(track.id)
        return True

    def lyrics_for(self, track) -> dict:
        return {"synced": False,
                "lines": [_LYRICS[i % len(_LYRICS)] for i in range(8)]}

    def devices(self) -> List[dict]:
        return [
            {"id": "this", "name": "Demo (this computer)", "active": True},
            {"id": "phone", "name": "iPhone (demo)", "active": False},
        ]

    def select_device(self, device: dict) -> None:
        pass

    # -- playback --------------------------------------------------------
    def play_tracks(self, tracks: List[Track], index: int, context: str) -> None:
        self._tracks = list(tracks)
        self._order = [index] + [i for i in range(len(tracks)) if i != index]
        self._pos = 0
        self.context_name = context or "Permify Mix"
        self._playing = True
        self._start = time.monotonic()

    def play_playlist(self, pl: Playlist) -> None:
        self.play_tracks(self.get_playlist_tracks(pl), 0, pl.name)

    def play_resume(self, uri: str, name: str, pos_ms: int) -> None:
        self.play_tracks(self._tracks, 0, name)

    def queue_play(self, index: int) -> None:
        pass

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
