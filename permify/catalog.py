from __future__ import annotations

import time
from typing import Dict, List, Optional

from .models import Album, Artist, Playlist, Track


def track_from_api(item: dict, liked: bool = False) -> Optional[Track]:
    """Accepts a bare track object or a wrapper like {'track': {...}}.

    After Spotify's Feb-2026 API migration, playlist entries are wrapped as
    {'item': {...}} instead of {'track': {...}} - so we accept both, and skip
    anything that isn't actually a track (e.g. podcast episodes).
    """
    if not item:
        return None
    t = None
    for key in ("track", "item"):
        if isinstance(item.get(key), dict):
            t = item[key]
            break
    if t is None:
        t = item
    if not t or not t.get("id"):
        return None
    if t.get("type", "track") not in ("track",):
        return None  # episode or other non-music entry
    album = t.get("album") or {}
    images = album.get("images") or []
    image_url = None
    if images:
        # Spotify returns sizes largest-first; grab the highest-res cover so
        # the art has the most detail to work with when we render it.
        image_url = images[0].get("url")
    # The wrapper carries the 'added on' timestamp for playlist/library
    # entries: e.g. {'added_at': '2021-05-04T12:00:00Z', 'item': {...}}.
    added_at = item.get("added_at") if isinstance(item, dict) else None
    return Track(
        id=t["id"],
        uri=t.get("uri", f"spotify:track:{t['id']}"),
        name=t.get("name", "?"),
        artists=", ".join(a.get("name", "") for a in t.get("artists", [])),
        album=album.get("name", ""),
        duration_ms=t.get("duration_ms") or 0,
        image_url=image_url,
        liked=liked,
        added_at=added_at,
    )


class Catalog:
    """Everything the Web API is good at: browsing the user's library."""

    def __init__(self, sp):
        self.sp = sp
        self._liked_cache: Dict[str, tuple] = {}  # id -> (flag, ts)
        self._me_name: Optional[str] = None

    # -- user ------------------------------------------------------------
    def me_name(self) -> str:
        if self._me_name:
            return self._me_name
        try:
            me = self.sp.current_user()
            self._me_name = me.get("display_name") or me.get("id") or "listener"
        except Exception:
            self._me_name = "listener"
        return self._me_name

    # -- playlists ---------------------------------------------------------
    def _api_token(self) -> str:
        am = getattr(self.sp, "auth_manager", None)
        tok = None
        if am is not None:
            try:
                tok = am.get_access_token(as_dict=False)
            except TypeError:
                tok = am.get_access_token()
        if isinstance(tok, dict):
            tok = tok.get("access_token")
        return tok

    def _get(self, url: str, params: dict) -> dict:
        import requests

        headers = {"Authorization": f"Bearer {self._api_token()}"}
        resp = requests.get(url, headers=headers, params=params, timeout=12)
        resp.raise_for_status()
        return resp.json()

    def playlists(self, cap: int = 100) -> List[Playlist]:
        out: List[Playlist] = []
        offset = 0
        while len(out) < cap:
            page = self.sp.current_user_playlists(limit=50, offset=offset)
            items = page.get("items") or []
            if not items:
                break
            for p in items:
                imgs = p.get("images") or []
                # Feb-2026 migration renamed the 'tracks' summary to 'items'
                listing = p.get("tracks") or p.get("items") or {}
                out.append(
                    Playlist(
                        id=p.get("id", ""),
                        uri=p.get("uri", ""),
                        name=p.get("name", "?"),
                        owner=(p.get("owner") or {}).get("display_name", ""),
                        count=listing.get("total", 0),
                        image_url=imgs[0].get("url") if imgs else None,
                    )
                )
            offset += len(items)
            if len(items) < 50:
                break
        return out

    def playlist_tracks(self, playlist_id: str, cap: int = 10000) -> List[Track]:
        """Uses /playlists/{id}/items - the post-Feb-2026 endpoint.

        Pages through the WHOLE playlist (not a fixed 500) so big playlists
        aren't cut off. Stops when Spotify reports we've seen every track
        ('total'), or after 'cap' as a hard safety limit.

        NB: Spotify only returns items for playlists you own or collaborate
        on; followed (other people's) playlists legitimately come back empty."""
        out: List[Track] = []
        offset = 0
        total = None
        while True:
            try:
                page = self._get(
                    f"https://api.spotify.com/v1/playlists/{playlist_id}/items",
                    {
                        "limit": 100,
                        "offset": offset,
                        "additional_types": "track",
                    },
                )
            except Exception:
                # last-resort fallback for very old spotipy/spotify combos
                page = self.sp.playlist_items(
                    playlist_id,
                    limit=100,
                    offset=offset,
                    additional_types=("track",),
                )
            if total is None:
                total = page.get("total") or 0
            items = page.get("items") or []
            if not items:
                break
            for it in items:
                tr = track_from_api(it)
                if tr:
                    out.append(tr)
            offset += len(items)
            if len(out) >= cap:
                break
            if total and len(out) >= total:
                break
            if len(items) < 100:
                break
        self.annotate_liked(out)
        return out

    # -- liked songs ---------------------------------------------------------
    def liked(self, cap: int = 10000) -> List[Track]:
        out: List[Track] = []
        offset = 0
        total = None
        while True:
            page = self.sp.current_user_saved_tracks(limit=50, offset=offset)
            if total is None:
                total = page.get("total") or 0
            items = page.get("items") or []
            if not items:
                break
            for it in items:
                tr = track_from_api(it, liked=True)
                if tr:
                    out.append(tr)
            offset += len(items)
            if len(out) >= cap:
                break
            if total and len(out) >= total:
                break
            if len(items) < 50:
                break
        return out

    # -- search ---------------------------------------------------------
    # Feb-2026 migration: /search still exists, but `limit` is capped at
    # 10 (was 50) and the default is 5. Asking for more makes Spotify
    # reject the WHOLE request - so we stay at <=10 and paginate instead.
    SEARCH_MAX = 10

    def search(self, query: str, cap: int = 30) -> List[Track]:
        """Tracks-only search, paginated around the new limit cap."""
        out: List[Track] = []
        offset = 0
        while len(out) < cap:
            batch = min(self.SEARCH_MAX, cap - len(out))
            res = self.sp.search(q=query, limit=batch, offset=offset, type="track")
            items = ((res or {}).get("tracks") or {}).get("items") or []
            for it in items:
                tr = track_from_api(it)
                if tr:
                    out.append(tr)
            if len(items) < batch:
                break
            offset += len(items)
        self.annotate_liked(out)
        return out

    def search_all(self, query: str, per: int = 10) -> dict:
        """Spotify-style rich search: artists, albums, playlists AND tracks."""

        per = max(1, min(self.SEARCH_MAX, per))
        out = {"artists": [], "albums": [], "playlists": [], "tracks": []}
        res = self.sp.search(q=query, limit=per, type="artist,album,playlist")
        if not res:
            return out
        for a in (res.get("artists") or {}).get("items") or []:
            if not a or not a.get("id"):
                continue
            imgs = a.get("images") or []
            out["artists"].append(
                Artist(
                    id=a["id"],
                    uri=a.get("uri", ""),
                    name=a.get("name", "?"),
                    image_url=(imgs[-1].get("url") if imgs else None),
                )
            )
        for a in (res.get("albums") or {}).get("items") or []:
            if not a or not a.get("id"):
                continue
            imgs = a.get("images") or []
            cover = (imgs[1] if len(imgs) > 1 else (imgs[0] if imgs else None)) or {}
            out["albums"].append(
                Album(
                    id=a["id"],
                    uri=a.get("uri", ""),
                    name=a.get("name", "?"),
                    artists=", ".join(x.get("name", "") for x in a.get("artists", [])),
                    image_url=cover.get("url"),
                    year=(a.get("release_date") or "")[:4],
                )
            )
        for p in (res.get("playlists") or {}).get("items") or []:
            if not p or not p.get("id"):
                continue
            imgs = p.get("images") or []
            listing = p.get("tracks") or p.get("items") or {}
            out["playlists"].append(
                Playlist(
                    id=p["id"],
                    uri=p.get("uri", ""),
                    name=p.get("name", "?"),
                    owner=(p.get("owner") or {}).get("display_name", ""),
                    count=listing.get("total", 0),
                    image_url=imgs[0].get("url") if imgs else None,
                )
            )
        # tracks get their own paginated pull so the section stays generous
        out["tracks"] = self.search(query, cap=25)
        return out

    def artist_top(self, artist) -> List[Track]:
        """GET /artists/{id}/top-tracks was REMOVED in Feb-2026.
        Closest thing left: tracks surfaced by an artist-scoped search."""
        name = getattr(artist, "name", "") or str(artist)
        out = []
        try:
            out = self.search(f'artist:"{name}"', cap=20)
        except Exception:
            out = []
        if not out:
            out = self.search(name, cap=20)
        return out

    def album_tracks(self, album_id: str, album_meta=None,
                     cap: int = 500) -> List[Track]:
        """Album tracks come back 'simplified' (no album block) - patch it."""
        out: List[Track] = []
        offset = 0
        while len(out) < cap:
            page = self.sp.album_tracks(album_id, limit=50, offset=offset)
            items = page.get("items") or []
            if not items:
                break
            for t in items:
                if not t or not t.get("id"):
                    continue
                out.append(
                    Track(
                        id=t["id"],
                        uri=t.get("uri", f"spotify:track:{t['id']}"),
                        name=t.get("name", "?"),
                        artists=", ".join(a.get("name", "") for a in t.get("artists", [])),
                        album=getattr(album_meta, "name", "") or "",
                        duration_ms=t.get("duration_ms") or 0,
                        image_url=getattr(album_meta, "image_url", None),
                    )
                )
            offset += len(items)
            if len(items) < 50:
                break
        self.annotate_liked(out)
        return out

    # -- listening history & taste ---------------------------------------
    def recently_played(self, cap: int = 30) -> List[Track]:
        page = self.sp.current_user_recently_played(limit=min(50, cap))
        items = (page or {}).get("items") or []
        out = [t for t in (track_from_api(i) for i in items) if t]
        self.annotate_liked(out)
        return out

    def top_tracks(self, limit: int = 20) -> List[Track]:
        """Your most-played tracks of the last ~4 weeks."""
        res = self.sp.current_user_top_tracks(limit=limit, time_range="short_term")
        items = (res or {}).get("items") or []
        out = [t for t in (track_from_api(i) for i in items) if t]
        self.annotate_liked(out)
        return out

    def top_artists(self, limit: int = 12) -> List[Artist]:
        res = self.sp.current_user_top_artists(limit=limit, time_range="long_term")
        out: List[Artist] = []
        for a in (res or {}).get("items") or []:
            if not a or not a.get("id"):
                continue
            imgs = a.get("images") or []
            out.append(
                Artist(
                    id=a["id"],
                    uri=a.get("uri", ""),
                    name=a.get("name", "?"),
                    image_url=(imgs[-1].get("url") if imgs else None),
                )
            )
        return out

    # -- playlist writing ---------------------------------------------------
    # Feb-2026 migration renamed /playlists/{id}/tracks -> /items. We try the
    # new shape first, then the legacy one, so both eras of the API work.
    def _request(self, method: str, url: str, body: Optional[dict] = None):
        import requests

        headers = {
            "Authorization": f"Bearer {self._api_token()}",
            "Content-Type": "application/json",
        }
        return requests.request(method, url, headers=headers, json=body, timeout=12)

    def create_playlist(self, name: str) -> Optional[Playlist]:
        # Feb-2026: POST /users/{id}/playlists -> POST /me/playlists
        body = {
            "name": name,
            "public": False,
            "description": "made in permify - windowed player by @johnthemailboy",
        }
        try:
            resp = self._request(
                "POST", "https://api.spotify.com/v1/me/playlists", body
            )
            if resp.status_code not in (200, 201):
                # legacy fallback for pre-migration servers
                me = self.sp.current_user() or {}
                uid = me.get("id")
                if not uid:
                    return None
                resp = self._request(
                    "POST",
                    f"https://api.spotify.com/v1/users/{uid}/playlists",
                    body,
                )
            if resp.status_code not in (200, 201):
                return None
            d = resp.json() or {}
            return Playlist(
                id=d.get("id", ""),
                uri=d.get("uri", ""),
                name=d.get("name", name),
                owner=self.me_name(),
                count=0,
            )
        except Exception:
            return None

    def add_to_playlist(self, playlist_id: str, track_uri: str) -> bool:
        base = f"https://api.spotify.com/v1/playlists/{playlist_id}"
        try:
            r = self._request("POST", f"{base}/items", {"uris": [track_uri]})
            if r.status_code in (200, 201):
                return True
            r = self._request("POST", f"{base}/tracks", {"uris": [track_uri]})
            return r.status_code in (200, 201)
        except Exception:
            return False

    def remove_from_playlist(self, playlist_id: str, track_uri: str) -> bool:
        base = f"https://api.spotify.com/v1/playlists/{playlist_id}"
        try:
            r = self._request("DELETE", f"{base}/items",
                              {"items": [{"uri": track_uri}]})
            if r.status_code in (200, 201):
                return True
            r = self._request("DELETE", f"{base}/tracks",
                              {"tracks": [{"uri": track_uri}]})
            return r.status_code in (200, 201)
        except Exception:
            return False

    # -- like state ---------------------------------------------------------
    # Feb-2026 consolidation: /me/tracks(+contains) -> generic /me/library.
    # We try the new endpoint first, then the legacy one, so both eras work.
    def _library_contains(self, uris: List[str]) -> List[bool]:
        try:
            import requests

            resp = requests.get(
                "https://api.spotify.com/v1/me/library/contains",
                headers={"Authorization": f"Bearer {self._api_token()}"},
                params={"uris": ",".join(uris)},
                timeout=12,
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return [bool(x) for x in data]
        except Exception:
            pass
        try:  # legacy shape (pre-migration)
            ids = [u.split(":")[-1] for u in uris]
            flags = self.sp.current_user_saved_tracks_contains(ids)
            return [bool(x) for x in flags]
        except Exception:
            return [False] * len(uris)

    def _library_modify(self, method: str, uris: List[str]) -> bool:
        try:
            return self._request(
                method,
                "https://api.spotify.com/v1/me/library?uris=" + ",".join(uris),
            ).status_code in (200, 201, 204)
        except Exception:
            return False

    def annotate_liked(self, tracks: List[Track]) -> None:
        now = time.time()
        todo = [t for t in tracks if now - self._liked_cache.get(t.id, (0, 0))[1] > 300]
        for i in range(0, len(todo), 38):  # /me/library/allows max 40 URIs
            batch = todo[i : i + 38]
            flags = self._library_contains([t.uri for t in batch])
            for t, flag in zip(batch, flags):
                t.liked = bool(flag)
                self._liked_cache[t.id] = (bool(flag), now)
        for t in tracks:
            cached = self._liked_cache.get(t.id)
            if cached is not None:
                t.liked = cached[0]

    @staticmethod
    def find_duplicates(tracks: List[Track]) -> List[Track]:
        """Return the 2nd+ occurrence of any track that appears more than once
        (matched by URI, falling back to name+artists). Callers can then
        remove those to dedupe a playlist."""
        seen: Dict[str, Track] = {}
        dupes: List[Track] = []
        for t in tracks:
            if not t:
                continue
            key = t.uri or f"{t.name}|{t.artists}".lower()
            if key in seen:
                dupes.append(t)
            else:
                seen[key] = t
        return dupes

    def set_liked(self, track: Track, flag: bool) -> bool:
        ok = self._library_modify("PUT" if flag else "DELETE", [track.uri])
        if not ok:  # legacy fallback
            if flag:
                self.sp.current_user_saved_tracks_add([track.id])
            else:
                self.sp.current_user_saved_tracks_delete([track.id])
        track.liked = flag
        self._liked_cache[track.id] = (flag, time.time())
        return flag
