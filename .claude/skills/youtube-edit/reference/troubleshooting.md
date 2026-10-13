# Troubleshooting and known quirks (tested on Windows 11, an RTX 3080, FFmpeg 7.1 gyan.dev full build, OBS 32.2)

| Area | Issue | What to do |
|---|---|---|
| FFmpeg | The `libplacebo` (Vulkan) filter crashes in this build. | Don't use it. Zooms use the `perspective` filter (sub-pixel, CPU, about 1× real time at 3440 px wide). |
| FFmpeg | "Fontconfig error: Cannot load default config file". | Harmless for captions, which use `fontsdir`. `drawtext` must be given an explicit `fontfile=` or it can crash. |
| FFmpeg | A filter graph with a looping still image (`-loop 1`) runs forever, or stretches a segment. | Give looping inputs `-t`, and use `shortest=1` on any overlay or alphamerge fed by them. `layout.py` does this; keep it that way. |
| FFmpeg | Paths in filter arguments break on `C:`. | Use `common.filter_path()`, which escapes the colon and backslashes. |
| Cuts | Audio/video drift after many cuts. | Cuts are snapped to frame boundaries and use trim/atrim + concat. Don't switch to `select`/`aselect`; aselect works on audio packets, not samples. |
| Parakeet | The first run is slow. | It's downloading the 2.4 GB model to the Hugging Face cache. Later runs take seconds to a minute. |
| Parakeet | CUDA out of memory. | `transcribe --chunk 120`. Chunks split at silences. |
| Parakeet | Brand or tool names come out wrong (e.g. "FVig" for FFmpeg). | Add `"corrections": {"FVig": "FFmpeg"}` to `plan.json` and re-run `captions` and `finish`. The fix survives re-cuts. |
| NeMo | Warnings about triton, OneLogger, Lhotse. | Harmless on Windows. |
| HyperFrames | A render takes 45 s longer and shows default text. | The template's script errored. See templates.md rules 4–6. To debug: `cd motion; npx hyperframes preview`, then open the browser console. |
| HyperFrames | chrome-headless-shell crashes (0xC0000409). | Set `VP_CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe`. |
| HyperFrames | Telemetry, skill auto-install, update checks. | `graphics.py` sets `HYPERFRAMES_NO_TELEMETRY`, `HYPERFRAMES_SKIP_SKILLS` and `HYPERFRAMES_NO_UPDATE_CHECK`. |
| HyperFrames | Upgrading. | Pinned at 0.8.150 in `motion/package.json`, and it releases several times a day. Upgrade on purpose: `cd motion; npm i hyperframes@<ver>`, then re-render a test graphic of each template. |
| research | Animated pages never "finish loading". | `research.py` uses a fixed `--timeout`, not `--virtual-time-budget`, which hangs. |
| OBS | `setup_obs` or `record` can't connect. | OBS must be open with the WebSocket server enabled. Check with `.\vp doctor --obs`. |
| OBS | The camera is white, black or 0×0 in "ISO Webcam". | Another app is holding the webcam (Windows lets only one app open it; face-tracking avatar apps do). Close it, or use ISO Avatar. Failing that, double-click "YT Webcam Cam" and pick the device, or set `recording.webcam_match` in `brand.json`. |
| OBS | The avatar is black in "ISO Avatar". | The avatar app (e.g. VSeeFace) isn't running or its virtual camera is off. "ISO Avatar" only exists if `recording.avatar_source` names an OBS source to copy. |
| OBS | OBS is still on the "YouTube ISO" profile after recording. | `.\vp setup_obs --restore`. |
| OBS | Your usual profile shows the wrong canvas after recording. | `--restore` repairs it from the values saved at `--use` (in `local/obs_state.json`). OBS also logs each profile's canvas at startup, in `%APPDATA%\obs-studio\logs`. |
| OBS | The recorded browser covers the camera slot, or the camera is missing. | OBS 32 stores scene layouts relative to the canvas that was active when they were placed, and rescales them when the canvas changes. `--use` re-lays the YouTube scene on the ISO canvas every time. Always start recordings with `--use`, not by picking the scene by hand. Your own scenes keep their relative layout (`*_rel` values), so they look the same back on 1920×1080. |
| Recording | The transcript is someone else (a video or stream that was playing), or track 1 is silent. | Track 1 ("YT Voice") must be your mic only: set `recording.voice_device` in `brand.json` to the device that carries only your voice, then `.\vp setup_obs`. If you route audio through a mixer such as Voicemeeter, send the mic to its own bus and record that bus. The app's sound is track 2 ("YT Chrome Audio"). Check with `ffprobe` that the recording has 2 audio streams. |
| Recording | `--use` says "Lock the window to record first". | Make exactly one window of `recording.screen_app` have a content area of exactly `recording.screen_size` (1920×1080 by default), e.g. with [FrameLock](https://github.com/anaremore/framelock). The message lists the windows it found and their sizes. |
| Recording | OBS captures the wrong Chrome window, or a black frame. | Run `--use` again with the locked window open; it points "YT Chrome" at that window's current title. Window capture uses the Windows 10+ (WGC) method, which Chrome needs; BitBlt captures are black. |
| OBS | "Source Cleanup Error … OBS Studio will now exit". | A plugin (Source Record, in testing) held a source while OBS changed scene collections. The YouTube scenes live in your main collection (`recording.obs_collection`) so recording never switches collections. |
| OBS | Something in your scene collection looks wrong after the YouTube setup. | `setup_obs` saves a copy of the collection before it first changes it, in `local/obs_backup/`. Only restore it with OBS closed. |
| Sync | `new_video` can't line up a `--cam` file ("confidence" too low). | One file has no or different audio. Make sure both recorded the same room sound, or pass `--cam-offset <seconds>`. Check a sync by itself with `python scripts/sync.py <screen> <cam>`. |
| Layout | The bubble covers code or a button. | Use `"mode": "screen"` for that span, or set the bubble's corner in `brand.json`. |
