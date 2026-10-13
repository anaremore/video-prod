# Music beds

Drop tracks here (mp3, wav, m4a, ogg or flac). **Name them by mood** so Claude can pick one when planning, for example `chill-lofi_calm_85bpm.mp3`, `upbeat-tech_energetic_120bpm.mp3`, `ambient-pad_focus.mp3`. Instrumental only: lyrics fight the voice.

## Free sources that are safe for monetized YouTube

| Source | License | Notes |
|---|---|---|
| **YouTube Audio Library** (YouTube Studio → Audio Library) | Free for YouTube videos, including monetized ones | Filter by "Attribution not required", or paste the attribution line it gives you into the description. This is the safest choice for YouTube. |
| **Pixabay Music** (pixabay.com/music) | Pixabay Content License: commercial use, no attribution | Some uploaders register tracks with Content ID. If a claim appears, dispute it with the Pixabay license. |
| **Free Music Archive / Incompetech** | Mostly CC BY | You must credit the artist in the description. Check each track's license. |

Avoid AI music generated with Meta's **MusicGen** for monetized videos: its model weights are licensed for non-commercial use only.

The pipeline loops a track to fill its span and ducks it under your voice automatically. The default level is -20 dB; set `volume_db` per track in `plan.json`.

## Sound effects

`assets/sfx/` has a starter set made by `.\vp make_sfx`: whoosh, swoosh-short, pop, click, riser. To replace them, use files with the same names, for example CC0 sounds from freesound.org.
