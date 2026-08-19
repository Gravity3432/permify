# Permify — GUI Roadmap

> Direction agreed with @johnthemailboy. This is the plan we're building to.

## Decided design
- **Layout:** Tabbed navigation **+** bottom player bar (Spotify-style)
- **Theme:** Keep periwinkle-violet identity for now; revisit "make it cooler" later
- **Devices:** Hybrid — stream here in the app **or** control other Spotify devices
- **Settings:** Full set (themes, layout, volume, device name, notifications, shortcuts, sleep timer)
- **Features to build (all):** Lyrics, Mini-player + notifications, Discover tab, Media keys + shortcuts

## Phases
### Phase 1 — Core restructure ✅
- [x] Tabbed navigation (sidebar: Home · Search · Library · Queue · Lyrics · Devices · Settings)
- [x] Bottom player bar (art, title/artist, seek, time, transport, volume, shuffle/repeat, like)
- [x] Keyboard shortcuts (Space, ←→, Ctrl+1..7, Ctrl+F/L, M)
- [x] Headless GUI smoke test (`test_gui.py`)

### Phase 2 — Settings tab ✅
- [x] Device name shown in Spotify
- [x] Default volume
- [x] Desktop notifications toggle (wired to config)
- [x] Keyboard shortcuts reference
- [ ] Layout selector (bottom bar / compact) — later
- [ ] Sleep timer — later
- [x] Theme note (revisit "cooler" look later)

### Phase 3 — Devices tab ✅ (hybrid-ready)
- [x] List available Spotify devices
- [x] Select/transfer to another device (via `engine.select_device`)
- [x] Show current playing device + status
- [x] Note that playing on this computer streams embedded audio

### Phase 4 — Lyrics view
- [ ] Static + synced lyrics while playing
- [ ] Auto-scroll with current line

### Phase 5 — Discover tab
- [ ] Top tracks, top artists, recently played
- [ ] Search filters (tracks / artists / albums / playlists)

### Phase 6 — Mini-player + notifications
- [ ] Always-on-top compact window
- [ ] Desktop notifications on track change

### Phase 7 — Media keys + shortcuts
- [ ] Multimedia keyboard play/pause/next/prev
- [ ] More keyboard shortcuts + a shortcuts popup

## Engine API available (already built)
`devices()`, `select_device()`, `lyrics_for()`, `set_liked()`, `top_tracks()`,
`top_artists()`, `recently_played()`, `create_playlist()`, `add_to_playlist()`,
`remove_from_playlist()`, `queue_remove()`, `queue_insert()`, `search_all()`,
`artist_top()`, `album_tracks()`, `play_resume()`, `play_playlist()`, `shuffle_toggle()`,
`repeat_cycle()`, `seek_ms()`, `set_volume()`, `volume_step()`.

> Made with ♥ by @johnthemailboy
