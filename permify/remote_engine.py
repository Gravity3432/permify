from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

from .catalog import Catalog, track_from_api
from .models import Playlist, Snapshot, Track


class RemoteEngine:
    """Controls an existing Spotify device via the Web API (Connect).

    Used when the embedded player is unavailable: drive your phone,
    a browser tab with open.spotify.com, a speaker… anything Spotify sees.
    """

    mode = "remote"

    def __init__(self, sp, cfg: dict):
        self.sp = sp
        self.catalog = Catalog(sp)
        self.cfg = cfg
        self._toast_cb: Callable[[str], None] = lambda m: None
        self._device_id: Optional[str] = None
        self._device_name = ""
        self._lock = threading.RLock()
        self._snap = Snapshot(device_label="searching for devices…")
        self._last_queue_fetch = 0.0
        self._queue: List[Track] = []
        self._context_name_cache: dict = {}
        self._playback_ctx_name = ""
        self._vol = int(cfg.get("volume", 60))

    # ------------------------------------------------------------- start
    def start(self, toast: Callable[[str], None]) -> None:
        self._toast_cb = toast
        self.refresh(force=True)
        if self._device_id is None:
            self._toast_cb(
                "no active Spotify device - press 'm' and pick one "
                "(open spotify.com or the app on your phone once)"
            )

    @property
    def me_name(self) -> str:
        return self.catalog.me_name()

    @property
    def device_label(self) -> str:
        return self._device_name or "no device"

    # ----------------------------------------------------------- devices
    def devices(self) -> List[dict]:
        try:
            return (self.sp.devices() or {}).get("devices") or []
        except Exception:
            return []

    def select_device(self, device: dict) -> None:
        try:
            self.sp.transfer_playback(device["id"], force_play=False)
            self._device_id = device["id"]
            self._device_name = device.get("name", "device")
            self._toast_cb(f"device: {self._device_name}")
        except Exception as exc:
            self._toast_cb(self._explain(exc))
        self.refresh(force=True)

    def _ensure_device(self) -> Optional[str]:
        if self._device_id:
            return self._device_id
        for d in self.devices():
            if d.get("is_active"):
                self._device_id = d["id"]
                self._device_name = d.get("name", "device")
                return self._device_id
        devs = self.devices()
        if devs:
            d = devs[0]
            self.select_device(d)
            return self._device_id
        return None

    # ----------------------------------------------------------- catalog
    def get_playlists(self):
        return self.catalog.playlists()

    def get_playlist_tracks(self, pl: Playlist):
        return self.catalog.playlist_tracks(pl.id)

    def get_liked(self):
        return self.catalog.liked()

    def search(self, q: str):
        return self.catalog.search(q)

    def search_all(self, q: str):
        return self.catalog.search_all(q)

    def artist_top(self, artist):
        return self.catalog.artist_top(artist)

    def album_tracks(self, album_id: str, album_meta=None):
        return self.catalog.album_tracks(album_id, album_meta)

    def artist_albums(self, artist, cap: int = 50):
        return self.catalog.artist_albums(getattr(artist, "id", artist), artist, cap)

    def artist_info(self, artist):
        return self.catalog.artist_info(artist)

    def follow_artist(self, artist, flag: bool) -> bool:
        return self.catalog.follow_artist(artist, flag)

    def is_following_artist(self, artist) -> bool:
        return self.catalog.is_following_artist(artist)

    def queue_play(self, index: int) -> None:
        # Remote mode can't reorder the queue (Spotify API limitation).
        pass

    def set_liked(self, track: Track, flag: bool) -> bool:
        return self.catalog.set_liked(track, flag)

    def get_bands(self):
        return None  # audio plays on another device - nothing local to analyze

    def lyrics_for(self, track):
        from . import lyrics

        return lyrics.fetch_lyrics(track)

    def recently_played(self):
        return self.catalog.recently_played()

    def top_tracks(self):
        return self.catalog.top_tracks()

    def top_artists(self):
        return self.catalog.top_artists()

    def create_playlist(self, name):
        return self.catalog.create_playlist(name)

    def add_to_playlist(self, playlist_id, track_uri):
        return self.catalog.add_to_playlist(playlist_id, track_uri)

    def remove_from_playlist(self, playlist_id, track_uri):
        return self.catalog.remove_from_playlist(playlist_id, track_uri)

    def play_resume(self, uri: str, name: str, pos_ms: int) -> None:
        dev = self._ensure_device()
        if not dev:
            self._toast_cb("no Spotify device found - press 'm'")
            return
        try:
            self.sp.start_playback(device_id=dev, uris=[uri],
                                   position_ms=max(0, int(pos_ms)))
            self._playback_ctx_name = "resumed session"
        except Exception as exc:  # noqa: BLE001
            self._toast_cb(self._explain(exc))
        self.refresh(force=True)

    # ---------------------------------------------------------- playback
    def _explain(self, exc) -> str:
        status = getattr(exc, "http_status", None)
        msg = str(exc)
        # --- authentication / token problems --------------------------
        if status == 401 or "token" in msg.lower() or "auth" in msg.lower():
            return ("login expired - run:  python -m permify --setup  "
                    "(or re-run it) to reconnect Spotify")
        if status == 403:
            return "spotify said no (a Premium account is required)"
        if status == 404:
            self._device_id = None
            return "no active device - press 'm' to pick one"
        if status == 429:
            return "spotify rate limit - wait a moment and retry"
        # --- network-level ---------------------------------------------
        if isinstance(exc, (ConnectionError, TimeoutError, OSError)) or \
                "timed out" in msg.lower() or "network" in msg.lower():
            return "can't reach spotify (check your internet)"
        # trim spotipy's wrapped noise to the useful tail
        if "SpotifyException" in msg or "requests" in msg.lower():
            for line in reversed(msg.splitlines()):
                line = line.strip()
                if line and "traceback" not in line.lower():
                    return f"spotify error: {line[:80]}"
        return f"spotify error: {msg[:80]}"

    def play_tracks(self, tracks: List[Track], index: int,
                    context_name: str) -> None:
        uris = [t.uri for t in tracks][:700]
        if not uris:
            return
        dev = self._ensure_device()
        if not dev:
            self._toast_cb("no Spotify device found - press 'm'")
            return
        try:
            self.sp.start_playback(
                device_id=dev, uris=uris, offset={"position": min(index, len(uris) - 1)}
            )
            self._playback_ctx_name = context_name
        except Exception as exc:  # noqa: BLE001
            self._toast_cb(self._explain(exc))
        self.refresh(force=True)

    def play_playlist(self, pl: Playlist) -> None:
        dev = self._ensure_device()
        if not dev:
            self._toast_cb("no Spotify device found - press 'm'")
            return
        try:
            self.sp.start_playback(device_id=dev, context_uri=pl.uri)
            self._context_name_cache[pl.uri] = pl.name
        except Exception as exc:  # noqa: BLE001
            self._toast_cb(self._explain(exc))
        self.refresh(force=True)

    # ------------------------------------------------------------ control
    def toggle(self) -> None:
        try:
            if self._snap.playing:
                self.sp.pause_playback(device_id=self._device_id)
            else:
                self.sp.start_playback(device_id=self._device_id)
        except Exception as exc:  # noqa: BLE001
            self._toast_cb(self._explain(exc))
        self.refresh(force=True)

    def next(self) -> None:
        try:
            self.sp.next_track(device_id=self._device_id)
        except Exception as exc:  # noqa: BLE001
            self._toast_cb(self._explain(exc))
        time.sleep(0.25)
        self.refresh(force=True)

    def prev(self) -> None:
        try:
            self.sp.previous_track(device_id=self._device_id)
        except Exception as exc:  # noqa: BLE001
            self._toast_cb(self._explain(exc))
        time.sleep(0.25)
        self.refresh(force=True)

    def seek_ms(self, ms: int) -> None:
        try:
            self.sp.seek_track(max(0, int(ms)), device_id=self._device_id)
        except Exception as exc:  # noqa: BLE001
            self._toast_cb(self._explain(exc))

    def seek_step(self, delta_ms: int) -> None:
        self.seek_ms(self._snap.position_ms + delta_ms)

    def set_volume(self, v: int) -> None:
        self._vol = max(0, min(100, int(v)))
        try:
            self.sp.volume(self._vol, device_id=self._device_id)
        except Exception as exc:  # noqa: BLE001
            self._toast_cb(self._explain(exc))

    def volume_step(self, delta: int) -> None:
        self.set_volume(self._vol + delta)

    def shuffle_toggle(self) -> bool:
        flag = not self._snap.shuffle
        try:
            self.sp.shuffle(flag, device_id=self._device_id)
            self._snap.shuffle = flag
        except Exception as exc:  # noqa: BLE001
            self._toast_cb(self._explain(exc))
        return flag

    def repeat_cycle(self) -> str:
        nxt = {"off": "context", "context": "track", "track": "off"}[self._snap.repeat]
        try:
            self.sp.repeat(nxt, device_id=self._device_id)
            self._snap.repeat = nxt
        except Exception as exc:  # noqa: BLE001
            self._toast_cb(self._explain(exc))
        return nxt

    # --------------------------------------------------------------- poll
    def refresh(self, force: bool = False) -> None:
        with self._lock:
            try:
                pb = self.sp.current_playback(additional_types="track")
            except Exception as exc:  # noqa: BLE001
                self._snap = Snapshot(
                    status="error",
                    message=self._explain(exc),
                    volume=self._vol,
                    device_label=self.device_label,
                )
                return
            if not pb:
                self._snap = Snapshot(
                    status="idle",
                    message="nothing playing - start something from " "this app or any Spotify app",
                    volume=self._vol,
                    device_label=self.device_label,
                )
                return
            dev = pb.get("device") or {}
            if dev.get("id"):
                self._device_id = dev.get("id")
                self._device_name = dev.get("name", self._device_name)
            track = track_from_api(pb.get("item"))
            if track:
                try:
                    self.catalog.annotate_liked([track])
                except Exception:
                    pass
            ctx = ((pb.get("context") or {}).get("uri")) or ""
            ctx_name = self._context_name_cache.get(ctx) or self._playback_ctx_name or (
                "Spotify" if not ctx else ctx.split(":")[-2] if ":" in ctx else "Spotify"
            )
            now = time.time()
            if now - self._last_queue_fetch > 4:
                self._last_queue_fetch = now
                try:
                    q = self.sp.queue() or {}
                    self._queue = [
                        t
                        for t in (track_from_api(i) for i in (q.get("queue") or [])[:24])
                        if t
                    ]
                except Exception:
                    pass
            self._vol = dev.get("volume_percent", self._vol)
            status = "playing" if pb.get("is_playing") else "paused"
            self._snap = Snapshot(
                track=track,
                playing=bool(pb.get("is_playing")),
                position_ms=pb.get("progress_ms") or 0,
                volume=self._vol,
                shuffle=bool(pb.get("shuffle_state")),
                repeat=pb.get("repeat_state") or "off",
                context_name=ctx_name,
                queue=list(self._queue),
                status=status,
                device_label=self.device_label,
                message="",
            )

    def snapshot(self) -> Snapshot:
        snap = self._snap
        # local interpolation so the progress bar glides between polls
        if snap.playing and snap.track:
            passed = 0  # kept simple; poll cadence is 2 s
            if passed:
                snap.position_ms = min(
                    snap.track.duration_ms, snap.position_ms + passed
                )
        return snap

    def shutdown(self) -> None:
        self.cfg["volume"] = self._vol
