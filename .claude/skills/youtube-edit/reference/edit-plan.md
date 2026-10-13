# plan.json — the edit plan

`videos/<slug>/plan.json` is the one file Claude writes by hand. Every time in it is in seconds on the
**flat-cut timeline**, the times shown in `work/flat_transcript.txt` and `work/flat_words.json`. They are
not raw-recording times. Re-running `cut.py` changes the timeline, so update the plan afterward.

```jsonc
{
  "title": "I Automated My Video Editing",          // working title (for chapters / description)
  "style": "bold",                                  // theme from motion/themes/themes.json (default: brand.json "style")

  "layout": {                                       // ISO recordings, or zooms on any recording
    "camera": "avatar",                             // framing preset from brand.json layout.cameras, e.g. "webcam"
    "segments": [
      { "start": 0,    "mode": "cam" },             // full camera: hook / intro
      { "start": 7.4,  "mode": "screen_cam", "view": "fit" },
      { "start": 95.0, "mode": "screen", "view": [1180, 160, 2260] },   // 16:9 window [x, y, width] in screen px
      { "start": 260,  "mode": "cam" }              // outro
    ],
    "zooms": "auto"                                 // from record.py clicks, or an explicit list:
    // "zooms": [ { "start": 30.2, "end": 34.0, "x": 2400, "y": 380, "scale": 2.0 } ]
  },

  "graphics": [
    { "id": "hook",   "template": "title-card",  "start": 0.4,  "duration": 2.6,
      "props": { "title": "Edit videos with AI", "subtitle": "100% local, 100% free" }, "sfx": "whoosh" },
    { "id": "me",     "template": "lower-third", "start": 3.2,
      "props": { "title": "Your Name", "subtitle": "Your tagline" } },
    { "id": "stack",  "template": "tool-cards",  "start": 21.0, "duration": 6,
      "props": { "heading": "The stack", "highlight": -1,
                 "items": [ { "role": "The editor", "name": "Claude Code" },
                            { "role": "The transcriber", "name": "Parakeet" } ] }, "sfx": "whoosh" },
    { "id": "ts",     "template": "callout",     "start": 33.8,
      "props": { "text": "Word-level timestamps", "label": "Why it matters", "position": "top-right" }, "sfx": "pop" },
    { "id": "site",   "template": "browser-frame", "start": 52.0, "duration": 5,
      "props": { "image": "research/hyperframes.png", "url": "hyperframes.heygen.com", "caption": "HyperFrames" } }
  ],

  "music": [
    { "file": "assets/music/lofi-chill.mp3", "start": 0, "end": null, "volume_db": -21 }
  ],
  "sfx": [ { "file": "click.wav", "at": 61.2 } ],

  "desktop_audio": true,                            // track 2 (computer sound) in the mix; false to drop it
  "desktop_audio_db": -6,
  "captions": true,
  "corrections": { "FVig": "FFmpeg", "hyper frames": "HyperFrames" },

  "chapters": [
    { "start": 0,   "title": "Intro" },
    { "start": 21,  "title": "The stack" },
    { "start": 95,  "title": "Live demo" }
  ]
}
```

## Fields

| Field | Notes |
|---|---|
| `layout.segments` | Each segment runs until the next `start`. Modes are `cam`, `screen` and `screen_cam` (screen with a round camera bubble). `cam` and `screen_cam` need an ISO recording. `view` is `"fit"` (whole screen) or `[x, y, width]`, a 16:9 window in screen pixels. Leaving out `layout` gives you `screen_cam` / `fit` throughout. |
| `layout.camera` | Which camera was recorded, as a framing preset name from `brand.json` → `layout.cameras` (`"webcam"` ships by default; add others such as `"avatar"` for a VTuber-style virtual camera). Tell cameras apart in the `--from flat` contact sheet. Override per video with `layout.cam_crop` `[x, y, w]` (16:9 window for `cam` shots) and `layout.bubble_crop` `[x, y, size]` (the bubble's square), both in camera pixels (1920×1080). |
| `layout.zoom_scale` | How far `"auto"` zooms go, relative to the segment's view (default `brand.json` → `layout.default_zoom`, 1.4). Keep the total, view × zoom, under about 1.8× for 1080p captures, or text gets soft. Zooms never leave the view, so anything a view frames out (browser bars, notices) stays out. |
| `layout.zooms` | `"auto"` gives Screen Studio-style zooms on click clusters, which needs `record.py`. A list gives exact zooms. Each zoom is `x, y` (screen px), `scale` (default 1.8) and `start/end`, easing in and out over 0.5 s. Keep zooms at least 1.5 s long and at least 1 s apart. |
| `style` | Graphics theme: `glass`, `clean`, `bold`, `neon`, `editorial`, or a brand theme you added (see `templates.md`). It restyles every graphic, the captions and the camera ring. `.\vp gallery` shows them all. |
| `graphics[]` | `id` must be unique; it's the render file name. `template` is a key of `motion/templates/templates.json`. `start` is when it appears; `duration` defaults per template. `props` are the template's variables. `sfx` names a sound in `assets/sfx` to play at `start`. |
| `highlight` placement | Prefer `"props": {"screen": [x, y, w, h]}`, in recorded-screen pixels: the click log's point, with the button's box read off a 40 px grid crop of the flat frame. `graphics` converts it to the final frame through the view and zoom. If it warns that a zoom moves the page while the highlight is up, use the duration it suggests. Example: `{ "id": "proceed", "template": "highlight", "start": 5.2, "duration": 1.6, "props": { "screen": [974, 953, 478, 58], "label": "", "dim": false } }` |
| `steps` | Re-use the tracker as the video advances, with `current` 0, 1, 2 and so on: `{ "template": "steps", "start": 7.5, "duration": 3, "props": { "steps": "Sign up, Configure, Launch", "current": 1 } }`. It sits at the top, so keep top-position callouts off at the same moment. |
| `music[]` | `file` is relative to the project root. It loops to fill `start`..`end` (`null` = until the end) and is ducked automatically under speech. `volume_db` defaults to the brand value (-20). Use several entries to change tracks between chapters. |
| `sfx[]` | Extra one-off hits: `file` (in `assets/sfx` or a path) and `at` (seconds). `volume_db` is optional. |
| `desktop_audio` / `desktop_audio_db` | Recordings from the OBS YouTube profile have **two audio tracks**: track 1 is the voice (transcribed, cut, cleaned up) and track 2 is the computer sound. Track 2 is cut the same way and mixed in at `desktop_audio_db` (default -6), dipping a little under speech. Use `false` when it's just noise (notifications, a video left playing). Pauses where the computer made sound are never auto-cut. |
| `captions` | `false` turns burned-in captions off for this video. |
| `corrections` | Misheard words → correct spelling, applied to captions. Matching is per single word, ignoring case and punctuation. Scan the transcript for product names, people and jargon; Parakeet often misspells brand names. |
| `chapters` | Become `final/chapters.txt` for the YouTube description. The first must start at 0, there must be at least 3, and each must be at least 10 s long. |

## Editorial rules of thumb

- **Hook first.** The first 5 seconds decide retention, so start on the strongest line. A short `title-card` on the hook works well.
- **Graphics land on the word.** Set `start` to the `s` of the word that triggers the graphic (from `flat_words.json`), or up to 0.2 s before it.
- **One thing at a time.** Don't overlap graphics. Leave at least 1 s between them, and keep a callout to about one every 20–30 s.
- **Full-screen graphics stay short,** 2.5–6 s. The voice continues underneath and captions hide automatically.
- **Use a lower third once,** the first time a person or product appears.
- **Use a `tool-cards` grid for lists of 3–8 things.** Step through them with `highlight: -1`, or spotlight the one being discussed.
- **Match `browser-frame` to the moment a site is named.** Capture it first with `research.py`.
- **Start a chapter with a `title-card`,** with a kicker such as "Step 2".
- **Keep music quiet.** Duck it well under the voice; the defaults do this. Avoid lyrics under talking.
- **Use SFX sparingly:** `whoosh` on full-screen transitions, `pop` on callouts, and nothing on lower thirds.
