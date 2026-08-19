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


class _Tk(_P):
    pass


class _Listbox(_P):
    def curselection(self, *a, **k):
        return (0,)
    def size(self, *a, **k):
        return 0


def _fake_tk():
    tk = types.ModuleType("tkinter")
    for name in ["Tk", "Frame", "Label", "Button", "Listbox", "Canvas",
                 "Entry", "Scale", "Checkbutton", "BooleanVar", "StringVar",
                 "Text", "Toplevel", "Menu", "PanedWindow", "Scrollbar"]:
        setattr(tk, name, _P(name))
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

    for tab in gui.NAV:
        app.switch_tab(tab)

    app.snap = engine.snapshot()
    app._update()
    app._toggle()
    app._seek(5)
    app._set_volume(70)
    app._toggle_like()
    app._dev_refresh()
    app.quit()
    print("PASS gui headless build (tabs + update + controls)")


def run_all():
    test_gui_builds_and_runs()
    print("\nGUI TESTS PASSED ✅")


if __name__ == "__main__":
    run_all()
