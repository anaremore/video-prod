---
name: youtube-edit
description: Edit a raw recording into a finished, on-brand YouTube video, entirely on this PC for free. Covers Parakeet transcription, cutting pauses, filler words and flubbed retakes, and screen + camera layouts with click zooms from OBS "ISO" recordings. Also HyperFrames motion graphics, word-highlight captions, ducked music and sound effects, a -14 LUFS export, chapters and a publish kit. Use whenever the user wants to edit, cut, caption, add graphics, music or zooms to, finish, or prepare to publish a video in this project, to record a new one with OBS, or to change the brand or graphic templates.
---

# YouTube editor

Turns a recording into a finished, on-brand video. Everything runs locally: there is no per-render cost, and footage never leaves the machine. An NVIDIA GPU makes transcription and encoding fast; without one it all still works, just slower.

| Role | Tool | Step |
|---|---|---|
| Editor (every judgment call) | **you** | cut decisions, `plan.json`, QA |
| Recorder | OBS "ISO wide canvas" + click logger | `setup_obs`, `record` |
| Transcriber | NVIDIA Parakeet (NeMo, GPU) | `transcribe` |
| Cutter | FFmpeg | `plan_cuts`, `cut` |
| Screen editor (camera / screen / bubble, zooms) | FFmpeg | `layout` |
| Researcher | WebSearch/WebFetch + headless Chrome screenshots | `research` |
| Animator | HyperFrames (HTML → video) | `graphics` |
| Captions | libass, word highlight | `captions` |
| Sound designer + finisher | FFmpeg (duck, mix, loudness, encode) | `finish` |

## Ground rules

- **Run steps with the `vp` runner from the project root** (the folder with `vp.cmd`): `.\vp <step> <slug> [options]` in PowerShell, `./vp.sh <step> <slug>` in Git Bash. It finds Python itself: `VP_PYTHON` if set, then `.venv` (made by `setup.ps1`), then a conda env named `videoprod`. The scripts are in this skill's `scripts/`. Each one has `--help`, and each prints the next step when it finishes.
- **Run `.\vp doctor` first** in a new session, or whenever something fails. Add `--obs` before recording.
- **Never modify or move the user's original recordings.** `new_video` hard-links them into the video folder.
- **All plan times are on the flat-cut timeline.** Use `work/flat_transcript.txt` and `work/flat_words.json`, never raw-recording times. Re-running `cut` shifts that timeline, so update `plan.json` afterward.
- **Look before you judge.** You can't hear the video, but you can see it. Use `snapshots` to build a contact sheet, then Read the PNG. Do this before choosing layouts and again before calling the video done.
- **Check in with the user at two points:** after the cut list (show the removals), and after the preview render (show the contact sheet and the preview path). Don't run the final render on a plan they haven't seen, unless they told you to go end to end.

## Folder map

```
brand/brand.default.json    shipped settings: colors, creator name, captions, layout, recording, audio + cuts
brand/brand.json            the user's overrides (gitignored), deep-merged over the defaults
motion/templates/           HyperFrames templates + templates.json (the catalog — read it when planning)
motion/themes/              looks (CSS) + themes.json; the user's own brand themes in themes.local.json (gitignored)
local/                      per-machine state (OBS state, OBS collection backups) — gitignored
assets/music, assets/sfx    music beds (user-supplied, see assets/music/README.md) and SFX
videos/<slug>/
  video.json  plan.json     recording facts / the edit plan you write
  source/                   hard link to the recording (+ clicks.json from record.py)
  work/                     transcripts, cuts.json, flat.mp4, base.mp4, captions.ass, snapshots/
  research/  gfx/  final/   screenshots / rendered graphics / finished video, chapters.txt, youtube.md
```

## Workflow

### 1. Ingest
```
.\vp new_video <slug> "<path to recording>"
```
Use a slug like `2026-10-claude-editing`. An OBS ISO recording (1920×2160: the size-locked Chrome window on top, camera below) is detected automatically, and so is `<recording>.clicks.json` from `record.py`.

**Audio:** OBS YouTube recordings have two audio tracks, track 1 your voice (`brand.json` → `recording.voice_device`) and track 2 Chrome's own sound. `new_video` reports them. Transcription uses only track 1, and track 2 is mixed in by `finish` (`desktop_audio` in the plan). If the transcript is someone else's voice, the mic routing is wrong; see `reference/recording.md`.

**Camera filmed on another device** (phone, camera)? Add `--cam "<camera file>"`. The camera is synced to the screen by audio, with drift corrected, and from then on it's treated exactly like an ISO recording.

**Recording a new video:** the first time only, `.\vp setup_obs` adds the "YouTube ISO" profile and scenes to OBS. Each time: lock the Chrome window to demo in at 1920×1080 (for example with [FrameLock](https://github.com/anaremore/framelock)). Then `.\vp setup_obs --use --scene "ISO Webcam"` (or `"ISO Avatar"`, if an avatar source is configured) points OBS at that window and switches over. Then `.\vp record` logs clicks while the user records. Afterwards, `.\vp setup_obs --restore` puts their usual OBS profile, scene and canvas back. The full guide is in `reference/recording.md`. Don't suggest the Source Record plugin; it was tested and is unreliable on OBS 32 (see recording.md).

### 2. Transcribe
```
.\vp transcribe <slug>
```
This uses Parakeet TDT 0.6B v2 (English) and writes `work/words.json` with word-level times, plus `work/transcript.txt`, which lists each line with its word indices (`w12-w30`). Pass `--model nvidia/parakeet-tdt-0.6b-v3` for other European languages. The first run downloads the model (about 2.4 GB). Long recordings are split at pauses automatically.

### 3. Cut (judgment)
```
.\vp plan_cuts <slug>                                   # auto cuts in the default "gentle" style
.\vp plan_cuts <slug> --style tight                     # jump-cut style (talking head / vlog)
.\vp plan_cuts <slug> --remove-words 21-28 --reason retake
.\vp plan_cuts <slug> --list                            # review; --restore N undoes removal #N
.\vp cut <slug>
```
**Cut styles** (`brand.json` → `cuts.styles`):
- **gentle (default):** for screen demos, where every cut makes the page jump. It cuts only pauses longer than 1 s, and leaves about 0.6 s of breathing room in each. It keeps "um"s, skips any cut shorter than 0.4 s, and never cuts while the mouse is moving, someone is typing, or the computer is playing sound.
- **tight:** for talking heads and vlogs: pauses over 0.45 s and fillers go.
- **none:** only the cuts you make.

Use gentle unless the user asks otherwise (or `brand.json` → `cuts.style` says so), and spend the cutting on content (retakes, chatter), not breaths.

**Always keep the intro and the sign-off.** The user's opening lines and closing lines are part of their format, even when they sound like casual chatter ("alright, let's try this…", "we'll stop there…"). `plan_cuts` refuses manual cuts in the first two and last two sentences. Only a flubbed retake inside them may go, with `--allow-ends --reason retake`. The cut preview's "Intro and sign-off" section must show nothing removed.

Read `work/transcript.txt` from top to bottom and remove:
- **Retakes.** When a sentence is started again, keep the last complete take and remove the earlier attempts by word range. Word-range removal also takes out the pause before, so the good take joins naturally.
- **F9 markers.** These come from `record.py` and appear in `cut_preview.txt`. Each means "I flubbed": remove the take just before it.
- **False starts, rambling asides and off-topic tangents** that don't serve the video. Be conservative here, and list anything debatable for the user rather than cutting it silently.
- **Not** natural pauses after a punchline or before a reveal. Restore one with `--restore` if the auto pass took it.

Read `work/cut_preview.txt`. Every kept sentence should read cleanly. Show the user a summary of the removals, then run `cut`. Pauses with on-screen activity (clicks or typing in the log) are never auto-cut, because that's the demo happening.

### 4. Look at the footage
```
.\vp snapshots <slug> --from flat --every 15
```
Read `work/snapshots/flat-sheet.png`. For an ISO recording you'll see the whole wide canvas, with the screen on top and the camera at the bottom left. Note:
- **Which camera was used:** set `"camera"` to the matching framing preset in `brand.json` → `layout.cameras` (`"webcam"` by default; the user may have added others, such as `"avatar"` for a virtual avatar camera). Check that the preset's framing still fits. If the person sits differently, set `cam_crop` or `bubble_crop` in the plan.
- **What's on screen when:** which page, and where the important area is, in Chrome pixels (1920×1080, top half of the canvas).
- **When the speaker is just talking to camera.**

### 5. Plan (judgment) → `videos/<slug>/plan.json`
Read `reference/edit-plan.md` for the schema and the editorial rules, and `motion/templates/templates.json` for the available graphics. Build the plan from `work/flat_transcript.txt` and `flat_words.json`:
- **Layout** (ISO recordings). Use `cam` for the hook, intro, opinions and outro. Use `screen_cam` (the default) for demos. Use `screen` when the bubble would cover something. Chrome is already 16:9 at 1080p, so `"fit"` shows the whole browser 1:1. Use a `[x, y, w]` view or a zoom for small text, or to cut the tab strip and address bar out of the frame. `"zooms": "auto"` uses the click log.
- **Style.** Set `"style"` to a theme from `motion/themes/themes.json`:
  - Looks: `glass`, `clean`, `bold`, `neon` or `editorial`.
  - Brand themes: any the user added in `themes.local.json` (or `themes.json`). If their notes say a project uses a brand theme, use it.

  One theme restyles every graphic, the captions and the camera ring. If the user is unsure, run `.\vp gallery` and show them `motion/gallery/<theme>.png`. For a new client, add a brand theme (see Extending).
- **Graphics.** Set each graphic's start to the time of the word it illustrates.
  - **Openers:** a hook `title-card` or `kinetic`.
  - **Introductions:** a `lower-third`, once.
  - **Key terms or numbers:** `callout`s.
  - **Lists:** `tool-cards`.
  - **Named sites:** `browser-frame`.
  - **Chapters:** a `title-card` at each.
  - **Closing:** an `end-card` (it needs a few seconds of video after the last words).
  - **Demos:** `highlight` around what's clicked, and `steps` to show progress through a flow.
- **Highlights from the click log.** Give a `highlight` `"screen": [x, y, w, h]` in recorded-screen pixels. The click log has the click point, and the button's box comes from a 40 px grid crop of the flat frame at that time. `graphics` converts it to the final frame through the view and any zoom. It also warns if a zoom moves the page while the highlight is up; shorten it as suggested.
- **Chrome's sound** (track 2). Keep it (`desktop_audio`, default -6 dB) when the demo's sound matters. Set it `false` when it's only notifications or a video left playing.
- **Music and SFX.** Pick a bed from `assets/music/` that fits the mood. Use `whoosh` on full-screen graphics and `pop` on callouts.
- **Chapters.** At least 3, the first at 0, each at least 10 s long.
- **`corrections`.** Map misheard words to the right spelling for captions, e.g. `{"FVig": "FFmpeg"}`. Always scan the transcript for product names, people and jargon.
Show the user the plan as a short list (time → what happens) before rendering.

### 6. Research
For each site or product named, use WebSearch/WebFetch to check facts and get the right URL, then:
```
.\vp research <slug> <url> --name <short-name>
```
That captures a screenshot to `research/<name>.png` for the `browser-frame` template. Read the PNG to check it. Redo it if a cookie banner or popup covers the page; `--wait` gives the page longer to load.

### 7. Render
```
.\vp graphics <slug>        # HyperFrames, about 20-30 s per graphic, 3 at a time, cached; uses the plan's style
.\vp layout <slug>          # ISO recordings, or any recording with zooms; writes work/base.mp4
.\vp captions <slug>        # word-highlight captions; hidden under full-screen graphics, raised above lower thirds
.\vp finish <slug> --preview
```
`layout` runs at roughly 1× real time when zooms are present, and faster otherwise. Run `layout` and `graphics` in the background for long videos.

### 8. QA (don't skip)
```
.\vp snapshots <slug> --from preview --graphics
.\vp snapshots <slug> --from preview --every 20
```
Read both sheets and check them against the **quality bar** below. Fix the plan or templates and re-render; cached graphics are skipped. Then give the user the path to `final/<slug>-preview.mp4` to watch.

### 9. Final + publish kit
```
.\vp finish <slug>
```
Confirm the printed loudness is the target, and that the final duration equals the flat-cut duration. Then write `final/youtube.md` containing:
- 3 title options (under 60 characters, front-loaded)
- a description: the hook line, 2–3 sentences, a "Tools mentioned" list with URLs from the research step, and the chapters from `final/chapters.txt`
- 10–15 tags
- a thumbnail idea: one frame time plus 3–4 words of text

## Quality bar

- [ ] The intro and sign-off are intact. The cut preview's "Intro and sign-off" section shows no removed words.
- [ ] The first 5 s carry the hook; nothing slow or "um" before it. Put a hook graphic over the intro rather than cutting it.
- [ ] No flubbed takes, doubled sentences or cut-off words. The cut preview reads like a script.
- [ ] Every graphic's text fits on screen and is spelled right, and the graphic appears on the word it illustrates. No two graphics overlap.
- [ ] Screen text is readable wherever the narration refers to it, through a view or a zoom.
- [ ] The camera bubble doesn't cover anything important. Switch that span to `screen` if it does.
- [ ] Captions don't cover key screen content. Raise or drop them for that span if they do, and they match the speech.
- [ ] Music sits under the voice, with no lyrics during talking, and fades out at the end.
- [ ] The finish step reports about -14 LUFS, the export is 1920×1080 H.264/AAC, and chapters.txt shows no warnings.

## When things go wrong

| Symptom | Fix |
|---|---|
| A graphic render takes ~45 s longer than the others, or shows default text | The template's script threw an error. Check names that clash with browser globals, a JSON prop that isn't a string, or a missing image. See `reference/templates.md`. |
| A graphic is blank or misplaced | CSS `transform` on an element GSAP animates. Position it with left/top instead. |
| `research` hangs or saves a blank page | Increase `--wait`, or set `VP_CHROME` to the full Chrome path. |
| CUDA out of memory in `transcribe` | `--chunk 120`. |
| Base video longer or shorter than the flat cut | Compare frame counts with ffprobe. Every overlay that has a looping input needs `shortest=1`. |
| Captions use the wrong font | `.\vp doctor` regenerates `motion/fonts/ttf`. |
| OBS connection refused | OBS must be open with the WebSocket server enabled (`.\vp doctor --obs`). |

More detail is in `reference/troubleshooting.md`.

## Extending

- **The user's settings:** `brand/brand.json`, which overrides `brand/brand.default.json` key by key (start from `brand/brand.example.json`). It holds the channel and creator name, the default `style`, colour or caption overrides that apply to every theme, the bubble, camera framing presets, the OBS/recording devices, loudness and the cut styles. Change `brand.default.json` only to change what everyone gets.
- **A new client or brand theme:** add an entry to `motion/themes/themes.local.json` (gitignored; same format as `themes.json`, merged over it) with `"css": "<one of the five looks>"`, the client's `colors` (sample them from their site in a recording frame), and `captions`. See `reference/templates.md`. Then run `.\vp gallery --themes <name>` and show the user the sheet.
- **A new look:** add `motion/themes/<name>.css`, which sets the variables from `themes/base.css` and restyles the `hf-*` blocks and the `hf-deco-*` decorations. Register it in `themes.json`, then check it in the gallery.
- **New graphic templates:** follow `reference/templates.md`, which covers the conventions and pitfalls. Add the template to `templates.json` and to `gallery.py` (`SAMPLES`), then check it across every theme with `.\vp gallery --templates <name>`.
- **Recording setup:** see `reference/recording.md`.
