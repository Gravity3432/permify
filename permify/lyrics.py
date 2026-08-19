from __future__ import annotations

"""Lyrics: synced lines via lrclib.net (free, LRC format), plain-text fallback
via genius.com when lrclib comes up empty.

Gracefully degrades: any network/lookup trouble just means "no lyrics"
for this track, never an app error.
"""

import bisect
import html as _html
import re
from typing import Dict, List, Optional, Tuple

_CACHE: Dict[str, dict] = {}

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _parse_lrc(lrc: str) -> List[Tuple[int, str]]:
    """Parse [mm:ss.xx] timestamps into [(ms, line)], sorted."""
    out: List[Tuple[int, str]] = []
    for line in lrc.splitlines():
        m = re.match(r"^\[(\d+):(\d+(?:\.\d+)?)\]\s?(.*)$", line.strip())
        if not m:
            continue
        ms = int(m.group(1)) * 60000 + int(float(m.group(2)) * 1000)
        out.append((ms, m.group(3).strip() or "♪"))
    out.sort(key=lambda x: x[0])
    return out


def _clean_lyric_html(seg: str) -> List[str]:
    seg = re.sub(r"<br\s*/?>", "\n", seg)
    seg = re.sub(r"<[^>]+>", "", seg)
    seg = _html.unescape(seg)
    return [ln.rstrip() for ln in seg.splitlines() if ln.strip()]


def _genius_lyrics(track) -> List[str]:
    """Plain (unsynced) lyrics scraped off a genius.com song page."""
    import requests

    q = f"{track.name} {(track.artists or '').split(',')[0].strip()}"
    search = requests.get(
        "https://genius.com/api/search/multi",
        params={"q": q, "per_page": 5},
        headers={"User-Agent": _UA, "Accept": "application/json"},
        timeout=6,
    )
    if search.status_code != 200:
        return []
    url: Optional[str] = None
    for section in (search.json().get("response", {}).get("sections") or []):
        if section.get("type") != "song":
            continue
        for hit in section.get("hits") or []:
            res = hit.get("result") or {}
            u = res.get("url")
            if u and "genius.com" in u and res.get("lyrics_state") != "instrumental":
                url = u
                break
        if url:
            break
    if not url:
        return []
    page = requests.get(url, headers={"User-Agent": _UA,
                                      "Accept-Language": "en-US,en;q=0.9"},
                        timeout=8)
    if page.status_code != 200:
        return []
    page_html = page.text
    lines: List[str] = []
    chunks = re.findall(
        r'<div data-lyrics-container="true"[^>]*>(.*?)</div>', page_html, re.S)
    if chunks:
        for seg in chunks:
            lines += _clean_lyric_html(seg)
    else:  # older page style
        m = re.search(r'<div class="lyrics">(.*?)</div>', page_html, re.S)
        if m:
            lines = _clean_lyric_html(m.group(1))
    # genius pages double up some ad-lib lines near instrumentals; trim junk
    junk = ("you might also like", "see ", "embed")
    return [ln for ln in lines
            if not any(ln.lower().startswith(j) for j in junk)]


def fetch_lyrics(track) -> dict:
    """Return {'synced': [(ms, line)], 'plain': [line], 'source': str}.
    Any bucket may be empty; source is where the winning text came from."""
    key = getattr(track, "id", None) or repr(track)
    if key in _CACHE:
        return _CACHE[key]
    res = {"synced": [], "plain": [], "source": ""}
    try:
        import requests

        resp = requests.get(
            "https://lrclib.net/api/get",
            params={
                "track_name": track.name,
                "artist_name": (track.artists or "").split(",")[0].strip(),
                "album_name": track.album or "",
                # lrclib wants seconds and gets grumpy if it's off by >2s
                "duration": max(1, round((track.duration_ms or 0) / 1000)),
            },
            headers={"User-Agent": "permify/0.1 (personal client by @johnthemailboy)"},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json() or {}
            if data.get("syncedLyrics"):
                res["synced"] = _parse_lrc(data["syncedLyrics"])
            if data.get("plainLyrics"):
                res["plain"] = [
                    ln for ln in data["plainLyrics"].splitlines() if ln.strip()
                ]
            if res["synced"] or res["plain"]:
                res["source"] = "lrclib"
    except Exception:
        pass
    if not res["synced"] and not res["plain"]:
        try:
            plain = _genius_lyrics(track)
            if plain:
                res["plain"] = plain
                res["source"] = "genius"
        except Exception:
            pass
    _CACHE[key] = res
    return res


def current_index(synced: List[Tuple[int, str]], pos_ms: int) -> int:
    """Index of the lyric line that should be highlighted at pos_ms."""
    if not synced:
        return 0
    times = [ms for ms, _ in synced]
    return max(0, min(len(synced) - 1, bisect.bisect_right(times, pos_ms) - 1))
