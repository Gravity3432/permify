from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Track:
    id: str
    uri: str
    name: str
    artists: str
    album: str
    duration_ms: int
    image_url: Optional[str] = None
    liked: bool = False
    added_at: Optional[str] = None  # "YYYY-MM-DDTHH:MM:SSZ" (Spotify)
    artist_uris: List[str] = field(default_factory=list)
    artist_ids: List[str] = field(default_factory=list)
    album_uri: str = ""

    @property
    def duration_text(self) -> str:
        total = max(0, self.duration_ms // 1000)
        return f"{total // 60}:{total % 60:02d}"

    @property
    def date_text(self) -> str:
        """Compact 'added on' date: '2021-05-04' (or '' if unknown)."""
        if not self.added_at:
            return ""
        return self.added_at[:10]


@dataclass
class Playlist:
    id: str
    uri: str
    name: str
    owner: str = ""
    count: int = 0
    image_url: Optional[str] = None
    kind: str = "playlist"  # 'playlist' or 'folder'


@dataclass
class Artist:
    id: str
    uri: str
    name: str
    image_url: Optional[str] = None
    followers: int = 0


@dataclass
class Album:
    id: str
    uri: str
    name: str
    artists: str = ""
    image_url: Optional[str] = None
    year: str = ""


@dataclass
class Snapshot:
    """Unified 'what is happening right now' returned by every engine."""

    track: Optional[Track] = None
    playing: bool = False
    position_ms: int = 0
    volume: int = 60
    shuffle: bool = False
    repeat: str = "off"  # off | context | track
    context_name: str = ""
    queue: List[Track] = field(default_factory=list)
    status: str = "idle"  # idle | buffering | playing | paused | error
    device_label: str = ""
    message: str = ""  # transient engine hint (e.g. 'buffering…')

    @property
    def duration_ms(self) -> int:
        return self.track.duration_ms if self.track else 0

    @property
    def position_text(self) -> str:
        return _fmt(self.position_ms)

    @property
    def duration_text(self) -> str:
        return _fmt(self.duration_ms)


def _fmt(ms: int) -> str:
    total = max(0, ms // 1000)
    return f"{total // 60}:{total % 60:02d}"
