"""Headless smoke test for the Permify GUI.

Fakes the `tkinter` module so the whole window can be built without a
display server, then exercises every tab, the update loop and the main
controls. Catches runtime errors in widget wiring.
"""
import os
import sys
import types

_parent = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _parent)


class _P:
    """Proxy: any attribute/method returns a proxy, so tkinter calls chain."""
    def __init__(self, name="proxy", *a, **k):
        self._name = name
    def __getattr__(self, item):
        return _P(f"{self._name}.{item}")
    def __call__(self, *a, **k):
        return self
    def config(self, *a, **k):
        return self
    def configure(self, *a, **k):
        return self
    def bind(self, *a, **k):
        return self
    def pack(self, *a, **k):
        return self
    def grid(self, *a, **k):
        return self
    def pack_propagate(self, *a, **k):
        return self
    def grid_rowconfigure(self, *a, **k):
        return self
    def grid_columnconfigure(self, *a, **k):
        return self
    def tkraise(self, *a, **k):
        return self
    def after(self, *a, **k):
        return 1
    def set(self, *a, **k):
        return self
    def get(self, *a, **k):
        return "0"
    def insert(self, *a, **k):
        return self
    def delete(self, *a, **k):
        return self
    def curselection(self, *a, **k):
        return ()
    def winfo_width(self, *a, **k):
        return 300
    def create_rectangle(self, *a, **k):
        return self
    def mainloop(self, *a, **k):
        return self
    def focus_set(self, *a, **k):
        return self
    def destroy(self, *a, **k):
        return self
    def update(self, *a, **k):
        return self


class _Base:
    """Real-ish class so ui.py can subclass Canvas/Frame etc."""
    def __init__(self, *a, **k):
        pass
    def __getattr__(self, item):
        return _P(item)
    def __call__(self, *a, **k):
        return self
    def __getitem__(self, item):
        return "#0f1115"
    def config(self, *a, **k):
        return self
    def configure(self, *a, **k):
        return self
    def bind(self, *a, **k):
        return self
    def pack(self, *a, **k):
        return self
    def grid(self, *a, **k):
        return self
    def pack_forget(self, *a, **k):
        return self
    def pack_propagate(self, *a, **k):
        return self
    def grid_rowconfigure(self, *a, **k):
        return self
    def grid_columnconfigure(self, *a, **k):
        return self
    def tkraise(self, *a, **k):
        return self
    def after(self, *a, **k):
        return 1
    def after_cancel(self, *a, **k):
        return self
    def set(self, *a, **k):
        return self
    def get(self, *a, **k):
        return "0"
    def insert(self, *a, **k):
        return self
    def delete(self, *a, **k):
        return self
    def curselection(self, *a, **k):
        return ()
    def winfo_width(self, *a, **k):
        return 300
    def winfo_height(self, *a, **k):
        return 200
    def winfo_children(self, *a, **k):
        return []
    def create_rectangle(self, *a, **k):
        return self
    def create_image(self, *a, **k):
        return self
    def create_window(self, *a, **k):
        return self
    def itemconfigure(self, *a, **k):
        return self
    def bbox(self, *a, **k):
        return (0, 0, 300, 200)
    def yview_scroll(self, *a, **k):
        return self
    def focus_set(self, *a, **k):
        return self
    def destroy(self, *a, **k):
        return self
    def update(self, *a, **k):
        return self


class _Listbox(_Base):
    def curselection(self, *a, **k):
        return (0,)
    def size(self, *a, **k):
        return 0


class _Tk(_Base):
    pass


def _fake_tk():
    tk = types.ModuleType("tkinter")
    for name in ["Tk", "Frame", "Label", "Button", "Listbox", "Canvas",
                 "Entry", "Scale", "Checkbutton", "BooleanVar", "StringVar",
                 "Text", "Toplevel", "Menu", "PanedWindow", "Scrollbar",
                 "PhotoImage"]:
        setattr(tk, name, type(name, (_Base,), {}))
    setattr(tk, "Listbox", _Listbox)
    setattr(tk, "Tk", _Tk)
    return tk


def test_gui_builds_and_runs():
    sys.modules["tkinter"] = _fake_tk()
    from permify.demo_engine import DemoEngine
    from permify import gui

    engine = DemoEngine()
    cfg = {"volume": 60, "device_name": "Permify", "notify": False,
           "auto_play": False, "shuffle": False}
    app = gui.PermifyGUI(engine, cfg, demo=True)

    for name in app.panels:
        app.switch_tab(name)

    app.snap = engine.snapshot()
    app._update()
    # render paths
    app._fill_library([])
    app._fill_home([], [], [], [])
    # search categories
    app.search_entry.delete(0, "end")
    app.search_entry.insert(0, "neon")
    for cat in ["All", "Tracks", "Artists", "Albums", "Playlists"]:
        app._search_cat(cat)
    # controls + features
    app._toggle()
    app._seek(5)
    app._vol_commit()
    app._toggle_like()
    app._dev_refresh()
    app._refresh_lyrics()
    app._sync_queue_now()
    # artist / album interaction
    artist = engine.top_artists()[0]
    album = engine.artist_albums(artist)[0]
    app._open_artist(artist)
    app._open_album(album)
    app.quit()
    print("PASS gui headless build (tabs + update + search + artist/album + controls)")


def run_all():
    test_gui_builds_and_runs()
    print("\nGUI TESTS PASSED ✅")


if __name__ == "__main__":
    run_all()
