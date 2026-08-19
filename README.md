# ♪ Permify

A **windowed Spotify player** — a real desktop app for your music, with a
distinct visual identity. Built on top of a battle-tested playback engine.

> made with ♥ by **@johnthemailboy**

---

## ✨ What it is

- 🪟 A proper **desktop window** (no terminal needed)
- 🎵 **Real embedded playback** — streams, decodes and plays Spotify audio
- 🎨 Clean dark theme with a periwinkle-violet accent
- 📁 Your playlists + Liked Songs
- 🔍 Search
- ▶️ Play / pause / next / prev / seek / volume / shuffle / repeat
- 🖼️ Album art, up-next queue

---

## 🚀 Run it

**Fastest on Windows — no build needed:** double-click **`run.bat`**. It
auto-installs everything, walks you through the one-time login, and opens
the app.

**Make a standalone app (`Permify.exe`):** double-click **`build.bat`** → get
`dist\Permify.exe`. Copy it anywhere, pin it to the taskbar.

**From source (macOS / Linux / WSL):**
```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m permify --demo           # offline demo, no account needed
python -m permify                  # the real thing
```

First real run walks you through the one-time Spotify login
(free Developer Client ID, redirect URI `http://127.0.0.1:4616/callback`).

---

## ⚠️ Requirements

- **Spotify Premium** (Spotify's rule for any third-party playback)
- Python 3.10+ (only needed to build/run from source; not for the `.exe`)

---

## 🗂 Layout

```
permify/
├── permify/          # the app package
├── entry.py          # exe entry point
├── permify.spec      # PyInstaller config
├── build.bat         # one-click -> Permify.exe
├── run.bat           # windows: just double-click to run
├── run.sh            # mac/linux launcher
└── requirements.txt
```

## 📜 Disclaimer

Permify is an **unofficial**, personal-use client, not affiliated with or
endorsed by Spotify. It only streams to your own Premium account.
