from __future__ import annotations

import io
import logging
import threading
import webbrowser
from typing import Callable, Optional

from . import config

log = logging.getLogger("termify.auth")

OGG_MAGIC = b"OggS"  # capture pattern every real OGG stream starts with


class _ChainStream:
    """Read a small already-verified head first, then the live stream.

    To spot a corrupt stream we have to read its first bytes up front, but
    the decoder still needs them - so this wrapper replays the head before
    continuing down the wire.
    """

    def __init__(self, head: bytes, rest):
        self._head = io.BytesIO(head) if head else None
        self._rest = rest

    def read(self, n: int = -1) -> bytes:
        if n == 0:
            return b""  # guard: librespot's size-less read = "the whole file"
        if self._head is not None:
            first = self._head.read(n)
            if n >= 0 and len(first) == n:
                return first
            self._head = None  # head exhausted
            if n < 0:
                return first + self._read_rest(-1)
            return first + self._read_rest(n - len(first))
        return self._read_rest(n)

    def _read_rest(self, n: int) -> bytes:
        if self._rest is None:
            return b""
        return self._rest.read(n)

    def close(self) -> None:
        for s in (self._head, self._rest):
            try:
                if s is not None:
                    s.close()
            except Exception:  # noqa: BLE001
                pass
        self._head = None
        self._rest = None

SUCCESS_HTML = """
<html><head><title>Termify</title><style>
body{background:#0b0b12;color:#e6e6f0;font-family:monospace;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0}
div{text-align:center;border:1px solid #47e08b;padding:32px 48px;border-radius:8px}
h1{color:#47e08b;letter-spacing:4px}
</style></head>
<body><div><h1>&#9835; TERMIFY</h1><p>Connected! You can close this tab<br>
and go back to your terminal.</p></div></body></html>
"""


# ---------------------------------------------------------------- Spotify web api

def build_spotify_client(cfg, interactive: bool = True):
    """Return an authenticated spotipy client.

    First run: opens a browser (PKCE flow) and asks Spotify for a token,
    cached under ~/.termify so you only do this once.
    """
    import spotipy
    from spotipy.oauth2 import SpotifyPKCE

    auth = SpotifyPKCE(
        client_id=cfg["client_id"],
        redirect_uri=config.REDIRECT_URI,
        scope=config.SCOPES,
        cache_path=str(config.SPOTIPY_CACHE),
        open_browser=interactive,
    )
    # get_access_token triggers the interactive flow the first time,
    # or silently refreshes a cached token afterwards.
    token = auth.get_access_token()
    if not token:
        raise RuntimeError("Could not get a Spotify access token.")
    return spotipy.Spotify(auth_manager=auth, requests_timeout=12, retries=2)


def prompt_client_id() -> str:
    print()
    print("  Termify needs a (free) Spotify Developer \"Client ID\":")
    print()
    print("   1. Go to  https://developer.spotify.com/dashboard  and log in")
    print("   2. Click       Create app")
    print(f"      Name:       termify            (anything)")
    print(f"      Redirect URI:  {config.REDIRECT_URI}")
    print("      (Important: add it exactly like that, then Save)")
    print("   3. Open the app's Settings and copy the  Client ID")
    print()
    cid = input("  Paste your Client ID here: ").strip()
    return cid


# ---------------------------------------------------------------- librespot (audio)

class CoreError(RuntimeError):
    pass


class CoreSession:
    """Wraps a librespot Session (the thing that can actually pull audio).

    Auth: the first time it runs librespot's own PKCE OAuth flow
    (browser opens on accounts.spotify.com, callback on 127.0.0.1:5588).
    Afterwards a stored credential (encrypted) is reused - no re-login.

    Construction may block on the network, so use it in a thread.
    """

    def __init__(self, cfg: dict, on_status: Optional[Callable[[str], None]] = None):
        self._cfg = cfg
        self._status = on_status or (lambda s: None)
        self.session = None
        self.error: Optional[Exception] = None
        self._ready = threading.Event()
        # Streams must not outlive their parent LoadedStream (it holds the
        # audio key + ciphers); if the parent is GC'd mid-decode the stream
        # goes corrupt -> "decoder: Invalid data" glitches. Pin them here.
        self._live_keep: list = []

    # -- life cycle ------------------------------------------------------
    def build_async(self) -> None:
        threading.Thread(target=self._build, daemon=True, name="core").start()

    def build_blocking(self, timeout: float = 90):
        self.build_async()
        return self.wait(timeout)

    def wait(self, timeout: float):
        if self._ready.wait(timeout):
            if self.session is not None:
                return self.session
        if self.error is not None:
            raise CoreError(str(self.error))
        raise CoreError("timed out connecting to Spotify")

    @property
    def ready(self) -> bool:
        return self.session is not None

    def _open_auth_page(self, url: str) -> str:
        self._status("opening Spotify login in your browser…")
        self._status(url)
        try:
            webbrowser.open(url)
        except Exception:
            pass
        print(f"\n  If your browser didn't open, visit:\n  {url}\n")
        return url

    def _build(self) -> None:
        try:
            logging.getLogger().setLevel(logging.CRITICAL)  # librespot is chatty
            from librespot.core import Session

            conf = (
                Session.Configuration.Builder()
                .set_stored_credential_file(str(config.LIBCRED_FILE))
                .set_store_credentials(True)
                .set_cache_enabled(False)
                .build()
            )
            builder = Session.Builder(conf)
            builder.set_device_name(str(self._cfg.get("device_name", "Termify")))
            have_creds = config.LIBCRED_FILE.exists()
            if not have_creds:
                self._status("first-time audio login…")
            # oauth() automatically falls back to the stored credential file
            # when it already exists, so this one call covers both cases.
            self.session = (
                builder.oauth(self._open_auth_page, SUCCESS_HTML).create()
            )
            self._status("audio core connected")
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self.error = exc
            self._status(f"audio core failed: {exc}")
        finally:
            self._ready.set()

    # -- audio fetch -----------------------------------------------------
    def _load_stream(self, uri: str, quality: str = "high"):
        """Shared loader: returns librespot's live chunked stream for a track."""
        from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
        from librespot.metadata import TrackId

        session = self.wait(30)
        q = {
            "normal": AudioQuality.NORMAL,
            "high": AudioQuality.HIGH,
            "very_high": AudioQuality.VERY_HIGH,
        }.get(quality, AudioQuality.HIGH)
        loaded = session.content_feeder().load_track(
            TrackId.from_uri(uri),
            VorbisOnlyAudioQuality(q),
            False,
            None,
        )
        return loaded

    def fetch_ogg(self, uri: str, quality: str = "high") -> bytes:
        """Download + decrypt one track -> VERIFIED OGG Vorbis bytes.

        Spotify occasionally answers with garbage instead of an OGG stream
        (bad key hand-off / CDN hiccup); decoding that dies on the very
        first bytes. Check the OggS magic and simply reload the track a few
        times before ever admitting defeat.
        """
        last_exc: Optional[Exception] = None
        for _ in range(3):
            try:
                loaded = self._load_stream(uri, quality)  # stays referenced during read()
                stream = loaded.input_stream.stream()
                data = stream.read()  # read() with no size = whole track
                if data and data[:4] == OGG_MAGIC:
                    return data
                last_exc = CoreError(
                    "empty stream" if not data else "stream was not OGG")
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        raise CoreError(f"could not load track: {last_exc}")

    def open_ogg_stream(self, uri: str, quality: str = "high"):
        """Open a track as a LIVE stream (chunks arrive on demand).

        The first bytes are pulled right away and verified against the OggS
        magic - a corrupt stream is thrown out and a FRESH one opened
        instead, so the decoder never sees garbage at track start (the
        classic 'Invalid data' failure). The verified head bytes are
        replayed into the decode via a _ChainStream.
        """
        last_exc: Optional[Exception] = None
        for _ in range(2):
            stream = None
            try:
                loaded = self._load_stream(uri, quality)
                stream = loaded.input_stream.stream()
                head = b""
                while len(head) < 4:
                    part = stream.read(4 - len(head))
                    if not part:
                        break
                    head += part
                if not head.startswith(OGG_MAGIC):
                    raise CoreError(f"stream is not OGG (starts {head[:8]!r})")
                chained = _ChainStream(head, stream)
                # pin the key-holding parent (GC'd LoadedStream = corrupt
                # stream mid-decode) and the wrapper itself
                self._live_keep.append(loaded)
                self._live_keep.append(chained)
                while len(self._live_keep) > 12:  # forget finished ones
                    self._live_keep.pop(0)
                return chained
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                try:
                    if stream is not None:
                        stream.close()
                except Exception:  # noqa: BLE001
                    pass
        raise CoreError(f"could not open stream: {last_exc}")
