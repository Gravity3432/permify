"""Offline tests for Permify's demo engine + GUI logic."""
import os, sys
_parent = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _parent)

from permify.demo_engine import DemoEngine
from permify.gui import _fmt


def test_demo_engine():
    e = DemoEngine()
    pls = e.get_playlists()
    assert len(pls) >= 1 and pls[0].name == "Demo Mix"
    tracks = e.get_playlist_tracks(pls[0])
    assert len(tracks) >= 7
    e.play_tracks(tracks, 0, "Demo Mix")
    snap = e.snapshot()
    assert snap.track is not None and snap.track.name
    e.next(); e.prev()
    e.toggle()
    e.set_volume(70); e.volume_step(-5)
    assert e.shuffle_toggle() is True
    assert e.repeat_cycle() == "context"
    assert e.search("neon") or e.search("sunset")
    assert e.me_name() == "demo listener"
    # rich data for the revamped GUI
    t = e.search("neon")[0]
    assert t.artist_uris and t.album_uri
    assert len(e.top_artists()) > 0
    assert e.artist_albums(e.top_artists()[0])
    assert e.lyrics_for(t)["lines"]
    assert e.devices()
    # album / artist page data
    a = e.top_artists()[0]
    al = e.artist_albums(a)[0]
    assert e.artist_top(a)
    assert e.album_tracks(al.id, al)
    print("PASS demo engine")


def test_gui_fmt():
    assert _fmt(0) == "0:00"
    assert _fmt(60000) == "1:00"
    assert _fmt(90061) == "1:30"
    print("PASS gui _fmt")


def test_config_permify_dir():
    import permify.config as c
    assert ".permify" in str(c.APP_DIR)
    assert c.REDIRECT_URI == "http://127.0.0.1:4616/callback"
    print("PASS config uses permify identity")


def run_all():
    test_demo_engine()
    test_gui_fmt()
    test_config_permify_dir()
    print("\nALL PERMIFY TESTS PASSED ✅")


if __name__ == "__main__":
    run_all()
