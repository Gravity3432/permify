"""Permify — a windowed Spotify player.

Entry point:  python -m permify   (or  permify  after install)
"""
from __future__ import annotations

import argparse
import sys

from . import __version__


def banner():
    print()
    print("  " + "=" * 40)
    print("   ♪  P E R M I F Y")
    print("   windowed spotify player")
    print("  " + "=" * 40)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(prog="permify",
                                     description="a windowed Spotify player")
    parser.add_argument("--demo", action="store_true",
                        help="offline demo with fake music (no account)")
    parser.add_argument("--setup", action="store_true",
                        help="re-run the one-time Spotify login")
    parser.add_argument("--version", action="version",
                        version=f"permify {__version__}")
    args = parser.parse_args()

    from . import config

    config.ensure_dirs()
    cfg = config.load_config()

    from . import auth

    # --- one-time login ---
    if args.setup:
        cfg["client_id"] = ""
        config.save_config(cfg)

    # build the engine
    if args.demo:
        from .demo_engine import DemoEngine
        engine = DemoEngine(cfg)
    else:
        if not cfg.get("client_id"):
            banner()
            print("  Permify needs a (free) Spotify Developer Client ID:")
            print("  1. https://developer.spotify.com/dashboard")
            print(f"  2. Create app, Redirect URI: {config.REDIRECT_URI}")
            print("  3. Copy the Client ID and paste it below.\n")
            try:
                cid = input("  Client ID: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  no Client ID entered.")
                return
            if not cid:
                print("  no Client ID - can't continue.")
                return
            cfg["client_id"] = cid
            config.save_config(cfg)
        print("  connecting to Spotify…")
        sp = auth.build_spotify_client(cfg, interactive=sys.stdin.isatty())
        # try embedded audio; else remote control
        from .audio_sink import PCMRing, pick_sink
        from .remote_engine import RemoteEngine
        from .stream_engine import StreamEngine
        core = None
        try:
            from .auth import CoreSession
            core = CoreSession(cfg)
            core.build_blocking(timeout=120)
        except Exception as e:
            print(f"  (embedded audio unavailable: {e})")
            core = None
        engine = None
        if core is not None and core.ready:
            try:
                pick_sink(PCMRing(), "auto")
                engine = StreamEngine(sp, cfg, core)
            except Exception as e:
                print(f"  (no audio backend: {e})")
        if engine is None:
            engine = RemoteEngine(sp, cfg)

    # --- launch the GUI ---
    from .gui import run
    try:
        run(engine, cfg, demo=args.demo)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n  could not open the window: {e}")
        print("  (Permify needs a graphical desktop to run.)")
        try:
            engine.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
