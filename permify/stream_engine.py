from __future__ import annotations

import io
import random
import threading
import time
from typing import Callable, List, Optional

from .audio_sink import (BaseSink, FFTAnalyzer, PCMRing, bytes_to_ms,
                         ms_to_bytes, pick_sink)
from .catalog import Catalog
from .models import Playlist, Snapshot, Track

PREBUFFER_BYTES = 150_000  # legacy default ~0.85 s; superseded by prebuffer_ms


class TeeReader:
    """Wraps a live stream: every byte read is also saved into `sink`, so a
    track streamed off the network becomes a full local copy we can later
    seek through (bytes for tests, librespot's chunked stream in real use)."""

    def __init__(self, raw, sink: bytearray):
        self.raw = raw
        self.sink = sink

    def read(self, n: int = -1) -> bytes:
        if n == 0:
            return b""  # librespot's read() with no/0 size means "the whole file"
        try:
            data = self.raw.read(n)
        except TypeError:
            data = self.raw.read() if n < 0 else self.raw.read(n)
        if data:
            self.sink += data
        return data

    def close(self) -> None:
        try:
            self.raw.close()
        except Exception:
            pass


def decode_chunks(source, start_ms: int = 0):
    """Yield int16 44.1 kHz stereo PCM bytes.

    `source` may be OGG Vorbis bytes OR a live file-like stream
    (read off the network, decoding chunks as they arrive).
    """
    import av

    if isinstance(source, (bytes, bytearray, memoryview)):
        container = av.open(io.BytesIO(bytes(source)), mode="r", format="ogg")
    else:
        container = av.open(source, mode="r", format="ogg")
    try:
        astream = next((s for s in container.streams if s.type == "audio"), None)
        if astream is None:
            raise RuntimeError("no audio stream found")
        resampler = av.AudioResampler(format="s16", layout="stereo", rate=44100)
        if start_ms > 0:
            # NB: without a stream arg, av seeks in AV_TIME_BASE (microseconds);
            # passing the stream would make it interpret the offset in stream ticks.
            container.seek(int(start_ms * 1000), backward=True)
        for frame in container.decode(astream):
            for res in resampler.resample(frame):
                data = res.to_ndarray().tobytes()
                if data:
                    yield data
        for res in resampler.resample(None):
            data = res.to_ndarray().tobytes()
            if data:
                yield data
    finally:
        try:
            container.close()
        except Exception:
            pass


class PCMPlayer:
    """Download-stream + decode + play one Spotify track; pause/seek included."""

    def __init__(self, volume01: float = 0.6, sink_preference: str = "auto",
                 on_event: Optional[Callable[[str], None]] = None,
                 prebuffer_ms: int = 250):
        self.ring = PCMRing()
        self.ring.analyzer = FFTAnalyzer()  # taps real audio for the visualizer
        self.sink: Optional[BaseSink] = None
        self._sink_pref = sink_preference
        self._on_event = on_event or (lambda e: None)
        self._lock = threading.RLock()
        self._generation = 0  # bumped on every load/seek; kills stale threads
        self.track: Optional[Track] = None
        self.state = "idle"  # idle | buffering | playing | paused | error
        self.error = ""
        self._decode_done = False
        self._seek_base_ms = 0
        self._ogg: Optional[bytes] = None
        self._volume01 = volume01
        self._rescues = 0      # self-heal attempts used for the current track
        self._fell_back = False  # True once any rescue kicked in (kept for tests)
        # The "how much audio must be queued before the first beat plays"
        # cushion. Can't be zero (the network would stutter the music),
        # but it can be tiny because decode keeps feeding the ring non-stop.
        self._prebuffer_bytes = max(16 * 1024, ms_to_bytes(int(prebuffer_ms)))

    # ---------------------------------------------------------- plumbing
    def _ensure_sink(self) -> BaseSink:
        if self.sink is None:
            self.sink = pick_sink(self.ring, self._sink_pref)
            self.sink.set_volume(self._volume01)
        return self.sink

    def _emit(self, event: str) -> None:
        try:
            self._on_event(event)
        except Exception:
            pass

    def _begin_output(self) -> None:
        sink = self._ensure_sink()
        sink.reset_played()
        try:
            sink.start()
        except Exception:
            # sounddevice may work at probe time but fail later (e.g. device
            # unplugged) - rebuild through the fallback chain.
            self.sink = pick_sink(self.ring, "external")
            self.sink.set_volume(self._volume01)
            self.sink.start()
        sink.set_paused(False)

    # ------------------------------------------------------------ loader
    def load_and_play(self, track: Track,
                      fetcher: Callable[[], bytes],
                      start_ms: int = 0,
                      stream_opener: Optional[Callable] = None,
                      fresh_fetcher: Optional[Callable] = None) -> None:
        with self._lock:
            self._generation += 1
            gen = self._generation
        self._stop_output_only()
        self.track = track
        self.state = "buffering"
        self.error = ""
        self._decode_done = False
        self._seek_base_ms = start_ms
        self._ogg = None
        self._rescues = 0
        self._fell_back = False
        threading.Thread(
            target=self._load_worker,
            args=(gen, track, fetcher, stream_opener, fresh_fetcher),
            daemon=True,
            name="pcm-loader",
        ).start()

    def _load_worker(self, gen: int, track: Track, fetcher,
                     stream_opener=None, fresh_fetcher=None) -> None:
        # Preferred path: decode straight off the network. Decoding begins
        # after librespot's first 128 KB chunk - sound in well under a second.
        if stream_opener is not None:
            try:
                live = stream_opener()
            except Exception:
                live = None  # couldn't open a stream; do the classic full fetch
            if live is not None:
                accum = bytearray()
                self._decode_worker(
                    gen, TeeReader(live, accum), self._seek_base_ms,
                    accum=accum, close_source=True,
                    stream_opener=stream_opener,
                    retry_fetcher=fresh_fetcher or fetcher)
                return
        self._fetch_and_decode(gen, track, fetcher,
                               stream_opener=stream_opener,
                               retry_fetcher=fresh_fetcher or fetcher)

    def _fetch_and_decode(self, gen: int, track: Track, fetcher,
                          stream_opener=None, retry_fetcher=None) -> None:
        """Classic path: whole-file download, then decode (used for prefetched
        tracks and as the streaming fallback)."""
        try:
            data = fetcher()
        except Exception as exc:  # noqa: BLE001
            if not self._stale(gen):
                if self._rescue(gen, stream_opener, retry_fetcher):
                    return
                self.state = "error"
                self.error = str(exc)
                self._emit("error")
            return
        if self._stale(gen):
            return
        if not data or data[:4] != b"OggS":
            # poisoned download (or a poisoned prefetch cache hit) - treat
            # exactly like a decode failure so the rescue ladder refetches.
            if self._rescue(gen, stream_opener, retry_fetcher):
                return
            self.state = "error"
            self.error = "decoder: downloaded data is not OGG"
            self._emit("error")
            return
        self._ogg = data
        self._decode_worker(gen, data, self._seek_base_ms,
                            retry_fetcher=retry_fetcher)

    def _rescue(self, gen: int, stream_opener, retry_fetcher) -> bool:
        """The music glitched (junk bytes, snapped connection): quietly
        restart the song from where we were instead of dying.

          - nothing played yet  -> open a FRESH live stream (fastest);
          - mid-song            -> classic whole-file download (seekable,
                                   reliable), resumed at the current spot.

        At most 3 rescues per track, then we admit defeat. Returns True if
        a rescue was kicked off.
        """
        if self._rescues >= 3:
            return False
        self._rescues += 1
        self._fell_back = True
        resume = self._seek_base_ms
        if self.state in ("playing", "paused") and self.sink:
            resume = max(0, self.position_ms() - 400)  # tiny overlap, no gap
        self._seek_base_ms = resume
        try:
            self.ring.clear()
            if self.sink:
                self.sink.set_paused(True)
                self.sink.reset_played()
        except Exception:  # noqa: BLE001
            pass
        self.state = "buffering"
        never_played = self.sink is None or self.sink.played_ms() == 0
        if (stream_opener is not None and resume == 0 and never_played
                and self._rescues == 1):
            try:
                live = stream_opener()
            except Exception:  # noqa: BLE001
                live = None  # open blew up - don't burn the attempt, go fetch
            if live is not None:
                accum = bytearray()
                self._decode_worker(gen, TeeReader(live, accum), 0,
                                    accum=accum, close_source=True,
                                    stream_opener=stream_opener,
                                    retry_fetcher=retry_fetcher)
                return True
        if retry_fetcher is not None:
            self._fetch_and_decode(gen, self.track, retry_fetcher,
                                   stream_opener=stream_opener,
                                   retry_fetcher=retry_fetcher)
            return True
        return False

    def _decode_worker(self, gen: int, source, start_ms: int,
                       accum: Optional[bytearray] = None,
                       retry_fetcher=None, close_source: bool = False,
                       stream_opener=None) -> None:
        self._decode_done = False
        try:
            for chunk in decode_chunks(source, start_ms):
                if self._stale(gen):
                    return
                if not self.ring.push(chunk):
                    return  # ring closed
                if self.state == "buffering" and self.ring.buffered() >= self._prebuffer_bytes:
                    try:
                        self._begin_output()
                    except Exception as exc:  # noqa: BLE001
                        if self._stale(gen):
                            return
                        self.state = "error"
                        self.error = f"audio output: {exc}"
                        self._emit("error")
                        return
                    if self.state == "buffering":
                        self.state = "playing"
                        self._emit("playing")
            if self._stale(gen):
                return
            self._decode_done = True
            if accum is not None and accum:
                # streamed bytes are fully local now - safe to seek anywhere
                self._ogg = bytes(accum)
            # If the track is shorter than the prebuffer, start anyway.
            if self.state == "buffering":
                try:
                    self._begin_output()
                    self.state = "playing"
                    self._emit("playing")
                except Exception as exc:  # noqa: BLE001
                    self.state = "error"
                    self.error = f"audio output: {exc}"
                    self._emit("error")
                    return
            self._watch_end(gen)
        except Exception as exc:  # noqa: BLE001
            if self._stale(gen):
                return
            # the live stream glitched (rare) - instead of dying, quietly
            # rescue the song and keep running from where we are.
            if self._rescue(gen, stream_opener, retry_fetcher):
                return
            self.state = "error"
            self.error = f"decoder: {exc}"
            self._emit("error")
        finally:
            if close_source:
                try:
                    source.close()
                except Exception:  # noqa: BLE001
                    pass

    def _watch_end(self, gen: int) -> None:
        """Spin in the loader thread until the sink has drained the ring."""
        while not self._stale(gen):
            if self._decode_done and self.state in ("playing", "paused"):
                if self.ring.buffered() < 32 * 1024:  # sink is draining; close enough
                    # wait for the tail to actually play out
                    tail_ms = bytes_to_ms(self.ring.buffered())
                    time.sleep(min(max(tail_ms / 1000.0, 0.1), 2.5))
                    if not self._stale(gen) and self._decode_done:
                        self.state = "idle"
                        self._emit("track_end")
                    return
            time.sleep(0.1)

    # ------------------------------------------------------------ control
    def toggle(self) -> None:
        if self.state == "playing":
            self.pause()
        elif self.state == "paused":
            self.resume()

    def pause(self) -> None:
        if self.sink and self.state == "playing":
            self.sink.set_paused(True)
            self.state = "paused"

    def resume(self) -> None:
        if self.sink and self.state == "paused":
            self.sink.set_paused(False)
            self.state = "playing"

    def seek(self, ms: int) -> None:
        if self._ogg is None or self.track is None:
            return
        ms = max(0, min(ms, max(0, self.track.duration_ms - 1000)))
        with self._lock:
            self._generation += 1
            gen = self._generation
        self.ring.clear()
        if self.sink:
            self.sink.reset_played()
        self._seek_base_ms = ms
        was_playing = self.state in ("playing", "buffering")
        self.state = "buffering"
        if self.sink:
            self.sink.set_paused(True)

        def rerun():
            self._decode_worker(gen, self._ogg, ms)
            if not was_playing and self.state == "playing":
                self.pause()

        threading.Thread(target=rerun, daemon=True, name="pcm-seek").start()

    def position_ms(self) -> int:
        if self.sink is None:
            return self._seek_base_ms
        pos = self._seek_base_ms + self.sink.played_ms()
        if self.track:
            return min(pos, self.track.duration_ms)
        return pos

    def set_volume(self, v01: float) -> None:
        self._volume01 = v01
        if self.sink:
            self.sink.set_volume(v01)

    def _stale(self, gen: int) -> bool:
        with self._lock:
            return gen != self._generation

    def _stop_output_only(self) -> None:
        self.ring.clear()
        if self.sink:
            self.sink.set_paused(True)
            self.sink.reset_played()  # new track's clock starts at zero

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
        self._stop_output_only()
        self.state = "idle"
        self.track = None

    def shutdown(self) -> None:
        self.stop()
        self.ring.close()
        if self.sink:
            self.sink.close()


# ---------------------------------------------------------------------------

class StreamEngine:
    """The real deal: streams audio straight from Spotify inside this terminal."""

    mode = "stream"

    def __init__(self, sp, cfg: dict, core):
        self.catalog = Catalog(sp)
        self.cfg = cfg
        self.core = core  # CoreSession
        self._toast_cb: Callable[[str], None] = lambda m: None
        self._volume = int(cfg.get("volume", 60))
        self.player = PCMPlayer(
            volume01=self._volume / 100.0,
            on_event=self._on_player_event,
            prebuffer_ms=int(cfg.get("prebuffer_ms", 250)),
        )
        self._lock = threading.RLock()
        self._tracks: List[Track] = []
        self._order: List[int] = []       # play order (indexes into _tracks)
        self._pos = 0                     # index into _order
        self.context_name = ""
        self.shuffle = False
        self.repeat = "off"
        self._auto_advance = threading.Lock()
        self._error_streak = 0  # consecutive track failures (circuit breaker)
        # sneakernet: the next song downloads while the current one plays,
        # so skipping ahead feels instant.
        self._prebuf: dict = {}           # uri -> decoded OGG bytes
        self._prebuf_pending = set()
        self._prebuf_lock = threading.Lock()

    # ------------------------------------------------------------- start
    def start(self, toast: Callable[[str], None]) -> None:
        self._toast_cb = toast
        if not self.core.ready:
            self._toast_cb("audio core is still connecting… first track may take a moment")

    @property
    def me_name(self) -> str:
        return self.catalog.me_name()

    @property
    def device_label(self) -> str:
        return f"{self.cfg.get('device_name', 'Termify')} (this app)"

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

    def set_liked(self, track: Track, flag: bool) -> bool:
        return self.catalog.set_liked(track, flag)

    # ---------------------------------------------------------- playback
    def play_tracks(self, tracks: List[Track], index: int,
                    context_name: str, start_ms: int = 0) -> None:
        if not tracks:
            return
        with self._lock:
            self._tracks = list(tracks)
            if self.shuffle:
                rest = [i for i in range(len(tracks)) if i != index]
                random.shuffle(rest)
                self._order = [index]
                self._order += rest
            else:
                self._order = [index]
                self._order += [i for i in range(len(tracks)) if i != index]
            self._pos = 0
            self.context_name = context_name
        self._start_current(announce=True, start_ms=start_ms)

    def play_resume(self, uri: str, name: str, pos_ms: int) -> None:
        """Pick up a previous session where we left off."""
        tr = next((t for t in self._tracks if t.uri == uri), None)
        if tr is None:
            tr = Track(
                id=uri.split(":")[-1], uri=uri,
                name=name or "resumed track", artists="", album="",
                duration_ms=0,
            )
        self.play_tracks([tr], 0, "resumed session", start_ms=pos_ms)

    def get_bands(self):
        """Live FFT levels of the actual audio (or None before sink runs)."""
        try:
            an = getattr(self.player.ring, "analyzer", None)
            return an.bands() if an else None
        except Exception:
            return None

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

    def play_playlist(self, pl: Playlist) -> None:
        tracks = self.get_playlist_tracks(pl)
        if not tracks:
            self._toast_cb(f"'{pl.name}' is empty")
            return
        self.play_tracks(tracks, 0, pl.name)

    def _current_track(self) -> Optional[Track]:
        if not self._order or self._pos >= len(self._order):
            return None
        return self._tracks[self._order[self._pos]]

    # ---------------------------------------------------- prefetch & fetch
    def _get_ogg(self, uri: str, quality: str) -> bytes:
        """Fetcher for the player: serve from the sneakernet cache if the
        next-radio gods have already warmed this URI up."""
        with self._prebuf_lock:
            hit = self._prebuf.pop(uri, None)
        if hit is not None and hit[:4] == b"OggS":
            return hit  # verified warm bytes
        # missing (or poisoned - would only ever fail at the very start):
        # pull a fresh, verified copy from Spotify instead
        return self.core.fetch_ogg(uri, quality)

    def _prefetch_next(self) -> None:
        with self._lock:
            nxt = None
            if self._order and self._pos + 1 < len(self._order):
                nxt = self._tracks[self._order[self._pos + 1]]
        if nxt is None:
            return
        with self._prebuf_lock:
            if nxt.uri in self._prebuf or nxt.uri in self._prebuf_pending:
                return
            self._prebuf_pending.add(nxt.uri)
        quality = self.cfg.get("quality", "high")

        def work():
            try:
                data = self.core.fetch_ogg(nxt.uri, quality)
                if data and data[:4] == b"OggS":  # never cache poison
                    with self._prebuf_lock:
                        # keep at most 3 tracks in the sneakernet cache
                        while len(self._prebuf) >= 3:
                            self._prebuf.pop(next(iter(self._prebuf)))
                        self._prebuf[nxt.uri] = data
            except Exception:  # noqa: BLE001
                pass  # prefetch is a bet, not a promise
            finally:
                with self._prebuf_lock:
                    self._prebuf_pending.discard(nxt.uri)

        threading.Thread(target=work, daemon=True, name="prefetch").start()

    def _start_current(self, announce: bool = False, start_ms: int = 0) -> None:
        track = self._current_track()
        if track is None:
            self.player.stop()
            return
        try:
            self.catalog.annotate_liked([track])
        except Exception:
            pass
        quality = self.cfg.get("quality", "high")
        with self._prebuf_lock:
            prewarmed = track.uri in self._prebuf
        self.player.load_and_play(
            track,
            fetcher=lambda: self._get_ogg(track.uri, quality),
            # rescues always bypass the sneakernet cache - it might be the
            # very thing that served us poisoned bytes.
            fresh_fetcher=lambda: self.core.fetch_ogg(track.uri, quality),
            start_ms=start_ms,
            # prefetched bytes decode instantly with no second download;
            # otherwise open a live stream straight from Spotify.
            stream_opener=None if prewarmed else
                          lambda: self.core.open_ogg_stream(track.uri, quality),
        )
        if announce:
            self._toast_cb(f"loading: {track.name}")
        self._prefetch_next()

    # ------------------------------------------------------------- events
    def _on_player_event(self, event: str) -> None:
        if event == "track_end":
            self._error_streak = 0
            self._advance(from_end=True)
        elif event == "playing":
            self._error_streak = 0  # something made sound - all is well
        elif event == "error":
            # Even after the player's own self-healing this track is dead.
            # Don't just sit in silence: skip it like every other player -
            # but bail out if EVERYTHING fails (probably the connection).
            self._error_streak += 1
            with self._lock:
                more = bool(self._order) and (
                    self._pos + 1 < len(self._order)
                    or self.repeat == "context")
            if more and self._error_streak < 3:
                bad = self._current_track()
                name = bad.name if bad else "that track"
                self._toast_cb(f"{name} won't play - skipping it ♪")
                self._advance(from_end=False)
            elif self._error_streak >= 3:
                self._toast_cb("playback keeps failing - check your internet "
                               "(press M for diagnostics)")
            else:
                self._toast_cb(self.player.error or "playback error")

    def _advance(self, from_end: bool = False) -> None:
        with self._auto_advance:  # only one advance at a time
            with self._lock:
                if self.repeat == "track" and from_end:
                    self.player.seek(0)
                    if self.player.state == "idle":
                        self._start_current()
                    return
                if self._pos + 1 < len(self._order):
                    self._pos += 1
                elif self.repeat == "context" and self._order:
                    self._pos = 0
                else:
                    self.player.stop()
                    return
            self._start_current()

    def next(self) -> None:
        with self._lock:
            if self._pos + 1 >= len(self._order) and self.repeat != "context":
                self._toast_cb("end of the list")
                return
            if self._pos + 1 < len(self._order):
                self._pos += 1
            else:
                self._pos = 0
        self._start_current()

    def queue_play(self, index: int) -> None:
        """Jump to the item shown 'index' places ahead in the up-next list."""
        with self._lock:
            target = self._pos + 1 + index
            if target >= len(self._order):
                return
            self._pos = target
        self._start_current()

    def queue_remove(self, index: int) -> bool:
        """Kick the item shown 'index' places ahead out of the play order."""
        with self._lock:
            target = self._pos + 1 + index
            if 0 <= target < len(self._order):
                self._order.pop(target)
                return True
        return False

    def queue_insert(self, track: Track, to_end: bool = False) -> None:
        """Slot a track into the play order: right after now (next), or end."""
        if not track:
            return
        with self._lock:
            # make sure the track object is in the context pool
            idx = next((i for i, t in enumerate(self._tracks)
                        if t.uri == track.uri), None)
            if idx is None:
                idx = len(self._tracks)
                self._tracks.append(track)
            if to_end:
                self._order.append(idx)
            else:
                self._order.insert(self._pos + 1, idx)
        name = f"'{track.name}'"
        if to_end:
            self._toast_cb(f"queued {name} at the end")
        else:
            self._toast_cb(f"{name} will play next")

    def prev(self) -> None:
        # >3 s in: restart the track like every other player
        if self.player.position_ms() > 3000:
            self.player.seek(0)
            return
        with self._lock:
            if self._pos > 0:
                self._pos -= 1
            else:
                self.player.seek(0)
                return
        self._start_current()

    def toggle(self) -> None:
        self.player.toggle()

    def seek_step(self, delta_ms: int) -> None:
        self.player.seek(self.player.position_ms() + delta_ms)

    def seek_ms(self, ms: int) -> None:
        self.player.seek(ms)

    # ------------------------------------------------------------- state
    def set_volume(self, v: int) -> None:
        self._volume = max(0, min(100, int(v)))
        self.player.set_volume(self._volume / 100.0)

    def volume_step(self, delta: int) -> None:
        self.set_volume(self._volume + delta)

    def shuffle_toggle(self) -> bool:
        self.shuffle = not self.shuffle
        with self._lock:
            if self._tracks:
                cur = self._order[self._pos] if self._order else 0
                rest = [i for i in range(len(self._tracks)) if i != cur]
                if self.shuffle:
                    random.shuffle(rest)
                self._order = [cur] + rest
                self._pos = 0
        return self.shuffle

    def repeat_cycle(self) -> str:
        modes = ["off", "context", "track"]
        self.repeat = modes[(modes.index(self.repeat) + 1) % 3]
        return self.repeat

    def snapshot(self) -> Snapshot:
        track = self._current_track()
        if track is not None:
            try:
                track.liked = track.liked
            except Exception:
                pass
        upcoming: List[Track] = []
        with self._lock:
            for i in range(self._pos + 1, min(self._pos + 101, len(self._order))):
                upcoming.append(self._tracks[self._order[i]])
        status = self.player.state
        message = ""
        if status == "buffering":
            message = "buffering…"
        elif status == "error":
            message = self.player.error
        return Snapshot(
            track=track,
            playing=self.player.state == "playing",
            position_ms=self.player.position_ms(),
            volume=self._volume,
            shuffle=self.shuffle,
            repeat=self.repeat,
            context_name=self.context_name,
            queue=upcoming,
            status=status,
            device_label=self.device_label,
            message=message,
        )

    def shutdown(self) -> None:
        self.cfg["volume"] = self._volume
        self.player.shutdown()
