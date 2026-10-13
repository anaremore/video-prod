# Recording: a size-locked Chrome window + camera in one OBS file (a free Tella)

Tella's main tricks are a separate screen and camera that you can re-lay out after recording, auto zooms, and cutting retakes. We get all of them for free:

| Tella feature | Ours |
|---|---|
| Separate screen + camera, change layout later | One OBS recording with **both views stacked on one canvas**. `layout.py` turns it into camera, browser, or browser + bubble per segment. Both views are in one file on one clock, so they can't drift. Separate per-source recording was tested and dropped; see "Why not Source Record?" below. |
| Record a specific window at an exact size | A window-locking tool such as [FrameLock](https://github.com/anaremore/framelock) keeps Chrome's content area at exactly 1920×1080. OBS captures that window, not the desktop, so notifications and other windows never show. |
| Auto zoom on clicks | `record.py` logs clicks in Chrome's pixels while OBS records; `"zooms": "auto"` in the plan. |
| Remove silences / filler | `plan_cuts.py` |
| Retakes | Press **F9** after a flub. `record.py` drops a marker, and Claude removes the take before it. |
| Backgrounds, captions | HyperFrames graphics; `captions.py`. |

## Canvas

```
+---------------- 1920 ----------------+
|                                      |
|   YT Chrome   (0,0)    1920 x 1080   |  the size-locked Chrome window (its whole content area,
|                                      |  tabs and address bar included)
+--------------------------------------+
|                                      |
|   Camera      (0,1080) 1920 x 1080   |  "YT Webcam Cam" or "YT Avatar Cam"
|                                      |
+--------------------------------------+   = 1920 x 2160, 30 fps
```
- **Audio track 1, "YT Voice":** your mic only (`recording.voice_device`).
- **Audio track 2, "YT Chrome Audio":** Chrome's own sound only, via OBS application audio capture.

These regions live in `brand/brand.default.json` → `recording` (`screen_app`, `screen_size`, `iso_canvas`, `screen`, `cam`); override any of them in your `brand/brand.json`. To record at a different size, change `screen_size`, `screen`, `cam` and `iso_canvas` together, run `.\vp setup_obs`, and lock Chrome to the new size.

## One-time setup

1. **OBS 30+** (tested on 32.2): Tools → WebSocket Server Settings → **Enable WebSocket server**, with authentication on. The scripts read the password from OBS's config, so you never type it.
2. **Tell the scripts about your devices** in `brand/brand.json` → `recording` (copy `brand/brand.example.json` to start):

   | Key | What | Default |
   |---|---|---|
   | `voice_device` | Start of the mic's name as OBS lists it. It must carry **only your voice**. | the system default input |
   | `webcam_match` | Text in the webcam's name, e.g. `"brio"` | the first camera |
   | `avatar_source` | Name of an existing OBS source to copy as the avatar camera (a VTuber app's virtual camera, say) | none: no "ISO Avatar" scene |
   | `obs_collection` | Your main scene collection; the scripts refuse to run in any other | whichever is open |
   | `recordings_folder` | Where OBS saves YouTube recordings | `~/Videos/YouTube` |

   **Mic routing:** if you use a mixer such as Voicemeeter, send the mic to its own bus (for example B2) and set `voice_device` to that bus's output ("VoiceMeeter Aux Output"). If track 1 also carries computer sound, transcription picks up whatever was playing.
3. `.\vp setup_obs` (try `--dry-run` first). It **adds**:
   - **Profile "YouTube ISO":** 1920×2160 at 30 fps, NVENC (x264 without an NVIDIA GPU), hybrid MP4, audio tracks 1+2, saving to `recordings_folder`.
   - **Scenes in your main collection:** **ISO Webcam**, and **ISO Avatar** if `avatar_source` is set.
     - Sources: "YT Chrome" (window capture, Windows 10+ method, content area only), "YT Webcam Cam" (at 1080p), "YT Avatar Cam" (a copy of your avatar source), "YT Voice" and "YT Chrome Audio".
     - The cameras only switch on while their scene is showing.

   Your existing scenes, sources and profiles are not modified. Recording only switches **profiles and scenes, never scene collections**. Before the first change, the collection's file is copied to `local/obs_backup/`.

**Avatar or webcam: pick one per video.** Windows lets only one app open a webcam, and face-tracking avatar apps hold it. For an avatar video, keep the avatar app's virtual camera on and use **ISO Avatar**. For a real-camera video, close the avatar app first and use **ISO Webcam**.

Framing presets for each camera are in `brand.json` → `layout.cameras` (`cam_crop` for full-camera shots, `bubble_crop` for the bubble). `brand.example.json` has an `avatar` preset that crops a full-body avatar to head and shoulders.

## Each recording

1. **Open the Chrome window you'll demo in.** A separate window or profile keeps your tabs out of the video. Set page zoom to around 125% so text reads well at 1080p.
2. **Lock that window's content area to 1920 × 1080** (in FrameLock: select the window, choose 1920 × 1080, **Add lock**). Lock only one Chrome window at that size.
3. `.\vp setup_obs --use --scene "ISO Webcam"` (or `"ISO Avatar"`). This:
   - finds the locked Chrome window (the Chrome window whose content is exactly 1920×1080) and points the video and Chrome-audio capture at it;
   - switches OBS to the YouTube ISO profile and checks the 1920×2160 canvas;
   - lays the scene out on that canvas (OBS 32 keeps layouts relative to the canvas they were made on, so this is redone every time);
   - mutes your collection's global Mic/Aux and Desktop Audio until `--restore`;
   - reports the captured size, and warns if it isn't 1920×1080.
4. In a terminal: `.\vp record`. Leave it running. It logs clicks inside the locked Chrome window, in Chrome's pixels, and follows the window if you move it.
5. Hit Record in OBS. When you flub a line, pause for a beat, press **F9**, and say the whole sentence again from its start.
6. Stop in OBS. `record.py` writes `<recording>.clicks.json` next to the video. Press Ctrl+C in that terminal; in PowerShell, answer **Y** to "Terminate batch job".
7. `.\vp setup_obs --restore` puts back your profile, scene, canvas and audio mutes.
8. Unlock the window if you like.
9. `.\vp new_video <slug> "<recordings folder>\<file>.mp4"`. The click log is picked up automatically.

Once OBS has hooked the Chrome window, it keeps capturing it as page titles change. Don't close that window mid-recording. If you do, OBS falls back to another Chrome window.

## Camera footage from another device

You might film yourself on a phone or a camera while OBS records Chrome. Keep both microphones on and run:
```
.\vp new_video <slug> "<chrome recording.mp4>" --cam "<camera.mp4>"
```
`new_video` lines up the camera with the screen by matching their audio. It measures near the start and again near the end, so it corrects clock drift too. `cut` then stacks them into the same layout as an ISO recording. Tested on synthetic footage: a +1.37 s offset and 0.04 % drift came out within about 11 ms. A file named `* cam*` in the same folder, finished within 20 s of the screen file, is picked up without `--cam`. If the audio can't be matched, pass `--cam-offset <seconds>`, measured as camera start minus screen start.

## Why not Source Record?

We tried the Source Record plugin (0.4.8) to save the camera as its own file during OBS recordings. With OBS 32.2.2:
- **NVENC encoder:** OBS crashed on 1 of 4 recording starts, inside NVIDIA's encoder (a known issue for the plugin).
- **x264 encoder:** stable, but it recorded the whole canvas instead of the camera.
- **Collection switches:** OBS shuts itself down ("Source Cleanup Error") when leaving a scene collection that uses the plugin.

Re-test it only if a newer release fixes NVENC support on OBS 32.

## Tips for quality

- **Sound beats picture.** Use a headset or close mic in a quiet room. Leave about 1 s of silence at the start so the auto cutter has a clean edge.
- **Make text big.** Use Chrome's page zoom at 125–150% while you demo. Zooms help, but big text helps more.
- **Clean the browser.** Use a separate Chrome window or profile, with no unrelated tabs, bookmarks bar off, and notifications muted. Don't show passwords, emails or customer data you wouldn't publish.
- **Move deliberately.** Click on what you're talking about. Clicks drive the auto zooms.
- **Tell the editor what happens next.** Say "let's look at …" before switching pages. It makes natural cut and layout points.
- **Recording a normal, non-ISO video** (camera only, a full-monitor capture, or any MP4)? That works too. Skip `setup_obs`; `layout` then only adds zooms.
