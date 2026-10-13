"""OBS setup for YouTube recording: a size-locked Chrome window + camera in one "ISO canvas".

    python setup_obs.py [--fps 30] [--folder D:/Recordings/YouTube] [--dry-run]   # create / repair
    python setup_obs.py --use --scene "ISO Avatar"   # switch OBS over to record ("ISO Avatar" | "ISO Webcam")
    python setup_obs.py --restore                    # back to your usual profile + scene

What gets recorded (profile "YouTube ISO", canvas 1920x2160, ONE file so nothing can drift):
  top     "YT Chrome"  — the Chrome window locked to 1920x1080 (brand.json recording.screen_size),
                         captured as a window (overlapping windows and notifications never show)
  bottom  the camera   — "YT Avatar Cam" (copied from an existing OBS source, recording.avatar_source — e.g. a
                         VTuber/virtual camera) or "YT Webcam Cam" (first webcam matching recording.webcam_match)
  track 1 "YT Voice"        — your mic (recording.voice_device; null = the system default input)
  track 2 "YT Chrome Audio" — Chrome's own sound only (OBS application audio capture)
layout.py later frames it (camera / Chrome / Chrome + bubble, click zooms).

Before --use: lock one Chrome window's content area to exactly 1920x1080, e.g. with FrameLock
(https://github.com/anaremore/framelock).
--use finds that window (the chrome.exe window whose client area is exactly 1920x1080), points the
capture at it, switches to the YouTube profile, lays the scene out on the 1920x2160 canvas (OBS 32 keeps
layouts relative to the canvas they were made on), and mutes the collection's global Mic/Aux + Desktop
Audio. --restore puts profile, scene, canvas and mutes back exactly.

The scenes live in your main scene collection (recording.obs_collection; null = whichever is open), so recording
switches only profiles and scenes, never scene collections. Your own scenes and sources are not modified, and
the collection's file is backed up to local/obs_backup/ before this first adds to it.
Needs OBS running with its WebSocket server on; the password is read from OBS's own config.

(Tried and dropped, 2026-10-12: separate camera files via the Source Record plugin — on OBS 32.2.2 it
crashed OBS or recorded the wrong source. Camera files from another device still work: new_video --cam.)
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from common import LOCAL, _has_nvenc, brand, load_json, log, obs_password, save_json

PROFILE = "YouTube ISO"
CAMS = {"Avatar": "YT Avatar Cam", "Webcam": "YT Webcam Cam"}
SCENES = {f"ISO {cam}": src for cam, src in CAMS.items()}
SCREEN = "YT Chrome"
VOICE = "YT Voice"             # track 1
APP_AUDIO = "YT Chrome Audio"  # track 2
OBSOLETE = ("YT Screen", "YT Desktop")  # earlier versions: full-monitor capture, all-desktop audio
STATE = LOCAL / "obs_state.json"  # profile + scene + canvas + mutes active before --use (personal, gitignored)
BACKUPS = LOCAL / "obs_backup"     # each scene collection's file as it was before this first added to it
SCENES_DIR = Path(os.path.expandvars(r"%APPDATA%\obs-studio\basic\scenes"))


def connect(a):
    import logging
    import obsws_python as obs
    logging.getLogger("obsws_python").setLevel(logging.CRITICAL)  # handled request errors are expected
    cl = obs.ReqClient(host=a.host, port=a.port, password=obs_password(), timeout=10)
    if cl.get_record_status().output_active:
        raise SystemExit("OBS is recording — stop it first.")
    return cl, obs


def main_collection(cl) -> str:
    want = brand()["recording"].get("obs_collection")
    now = cl.get_scene_collection_list().current_scene_collection_name
    if not want:  # not configured: use whatever collection is open (set it in brand.json to pin it)
        return now
    if now != want:
        raise SystemExit(f"OBS is on scene collection '{now}'. Switch to '{want}' in OBS (Scene Collection menu) "
                         "and run this again.")
    return want


def video(cl) -> dict:
    v = cl.get_video_settings()
    return {"fps_num": v.fps_numerator, "fps_den": v.fps_denominator, "base_w": v.base_width,
            "base_h": v.base_height, "out_w": v.output_width, "out_h": v.output_height}


def ensure_video(cl, want: dict, label: str) -> None:
    """After a profile switch, make sure the canvas really is the profile's (OBS can keep the old one)."""
    if video(cl) != want:
        cl.set_video_settings(want["fps_num"], want["fps_den"], want["base_w"], want["base_h"],
                              want["out_w"], want["out_h"])
        log(f"  (repaired {label} canvas: {want['base_w']}x{want['base_h']} @ {want['fps_num']}/{want['fps_den']})")


def place(cl, scene: str, source: str, x: int, y: int, w: int, h: int) -> None:
    item_id = cl.get_scene_item_id(scene, source).scene_item_id
    cl.set_scene_item_transform(scene, item_id, {
        "positionX": x, "positionY": y, "alignment": 5,  # anchor top-left
        "boundsType": "OBS_BOUNDS_SCALE_INNER", "boundsWidth": w, "boundsHeight": h, "boundsAlignment": 0})


def layout_scene(cl, scene: str) -> None:
    """Place Chrome + camera in pixels of the ISO canvas. OBS 32 stores item layouts relative to the
    canvas active when they were placed and rescales them when the canvas changes, so this must run
    while the YouTube ISO canvas is active — --use does it every time, right after switching."""
    rec = brand()["recording"]
    place(cl, scene, SCREEN, *rec["screen"])
    place(cl, scene, SCENES[scene], *rec["cam"])


def backup_collection(name: str) -> None:
    """Copy the collection's file before the first change, so the setup can always be undone (with OBS closed)."""
    import shutil
    stem = name.replace(" ", "_")
    if any(BACKUPS.glob(f"{stem}.before-youtube-scenes.*.json")):
        return
    for f in sorted(SCENES_DIR.glob("*.json")):
        try:
            if json.loads(f.read_text(encoding="utf-8")).get("name") != name:
                continue
        except (OSError, json.JSONDecodeError):
            continue
        BACKUPS.mkdir(parents=True, exist_ok=True)
        dest = BACKUPS / f"{stem}.before-youtube-scenes.{time.strftime('%Y-%m-%d')}.json"
        shutil.copy2(f, dest)
        return log(f"  backed up scene collection '{name}' -> {dest}")
    log(f"  WARNING: couldn't find the file for scene collection '{name}' to back it up")


def find_source(source_name: str) -> tuple[str, dict] | None:
    """An existing source's kind + settings from any OBS scene collection on disk."""
    for f in sorted(SCENES_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for s in data.get("sources", []):
            if s.get("name") == source_name:
                return s["id"], s.get("settings", {})
    return None


def locked_target() -> dict:
    from winutil import describe, locked_window
    rec = brand()["recording"]
    app, size = rec.get("screen_app", "chrome.exe"), tuple(rec.get("screen_size", rec["screen"][2:]))
    w = locked_window(app, size)
    if not w:
        raise SystemExit(f"Lock the window to record first: lock one {app} window's content area (e.g. with FrameLock) "
                         f"to {size[0]}x{size[1]}. (Found: {describe(app, size)}.)")
    return w


def use(a) -> None:
    cl, _ = connect(a)
    main_collection(cl)
    if a.restore:
        prev = load_json(STATE, default={})
        if not prev:
            raise SystemExit("Nothing to restore (no previous OBS state saved).")
        if cl.get_profile_list().current_profile_name != prev["profile"]:
            cl.set_current_profile(prev["profile"])
            time.sleep(0.5)
        if prev.get("video"):
            ensure_video(cl, prev["video"], f"'{prev['profile']}'")
        if prev.get("scene"):
            cl.set_current_program_scene(prev["scene"])
        if prev.get("muted_before"):
            for name, muted in prev.pop("muted_before").items():
                try:
                    cl.set_input_mute(name, muted)
                except Exception:  # noqa: BLE001 — input renamed/removed since
                    pass
            save_json(STATE, prev)
        log(f"OBS restored: profile '{prev['profile']}', scene '{prev.get('scene')}'.")
        return

    scene = a.scene or "ISO Webcam"
    if scene not in SCENES:
        raise SystemExit(f"Unknown scene '{scene}'. Use one of: {', '.join(SCENES)}")
    if scene not in [s["sceneName"] for s in cl.get_scene_list().scenes]:
        raise SystemExit(f"Scene '{scene}' doesn't exist yet — run setup_obs.py first.")
    target = locked_target()

    profile = cl.get_profile_list().current_profile_name
    if profile != PROFILE:
        here = cl.get_current_program_scene().scene_name
        prev_scene = load_json(STATE, default={}).get("scene") if here in SCENES else here  # never "restore" to ours
        save_json(STATE, {"profile": profile, "scene": prev_scene, "video": video(cl)})
        cl.set_current_profile(PROFILE)
        time.sleep(0.5)
    w, h = brand()["recording"]["iso_canvas"]
    ensure_video(cl, {"fps_num": a.fps, "fps_den": 1, "base_w": w, "base_h": h, "out_w": w, "out_h": h}, f"'{PROFILE}'")

    # Point video + audio capture at the locked window: match its exact title now; once hooked, OBS keeps
    # the window as page titles change (priority 2 = otherwise any window of the same program).
    from winutil import obs_window_id
    wid = obs_window_id(target)
    cl.set_input_settings(SCREEN, {"window": wid, "priority": 2, "method": 2, "client_area": True, "cursor": True}, True)
    cl.set_input_settings(APP_AUDIO, {"window": wid, "priority": 2}, True)
    layout_scene(cl, scene)
    cl.set_current_program_scene(scene)

    # The YouTube scenes carry their own audio (YT Voice -> track 1, YT Chrome Audio -> track 2), so the
    # collection's global Mic/Aux + Desktop Audio are muted while recording and restored afterwards.
    special = [n for n in cl.send("GetSpecialInputs", raw=True).values() if n]
    state = load_json(STATE, default={})
    if "muted_before" not in state:
        state["muted_before"] = {n: cl.get_input_mute(n).input_muted for n in special}
        save_json(STATE, state)
    for n in special:
        cl.set_input_mute(n, True)
    for n in (VOICE, APP_AUDIO):
        cl.set_input_mute(n, False)

    time.sleep(1.0)
    item = next(i for i in cl.get_scene_item_list(scene).scene_items if i["sourceName"] == SCREEN)
    got = (int(item["sceneItemTransform"]["sourceWidth"]), int(item["sceneItemTransform"]["sourceHeight"]))
    log(f"  recording '{target['title'][:60]}' ({got[0]}x{got[1]})")
    if got != tuple(target["client"][2:]):
        log(f"  WARNING: OBS captures {got[0]}x{got[1]}, expected {target['client'][2]}x{target['client'][3]} — "
            "check the YT Chrome source in OBS before recording.")
    log(f"OBS ready to record: profile '{PROFILE}', scene '{scene}'. "
        "Run record.py, then hit Record. Afterwards: setup_obs.py --restore")


def create(a) -> None:
    rec = brand()["recording"]
    cx, cy, cw, ch = rec["cam"]
    iso_w, iso_h = rec["iso_canvas"]
    avatar = find_source(a.avatar_source)
    encoder = "nvenc" if _has_nvenc() else "x264"
    log(f"Profile '{PROFILE}': {iso_w}x{iso_h} @ {a.fps} fps, {encoder}, hybrid MP4, 2 audio tracks -> {a.folder}")
    log(f"Scenes in '{rec.get('obs_collection') or 'the open scene collection'}': {SCREEN} {rec['screen']}, camera {rec['cam']}; "
        f"avatar = {'copy of ' + repr(a.avatar_source) if avatar else 'SKIPPED'}; webcam = first device matching "
        f"'{a.webcam_match}'; audio: {VOICE} ({rec['voice_device']}) -> track 1, {APP_AUDIO} (Chrome) -> track 2")
    if a.dry_run:
        return
    cl, obs = connect(a)
    backup_collection(main_collection(cl))

    before = cl.get_profile_list().current_profile_name
    Path(a.folder).mkdir(parents=True, exist_ok=True)
    try:  # CreateProfile switches to the new profile; always put the user's back
        if PROFILE not in cl.get_profile_list().profiles:
            cl.create_profile(PROFILE)
        elif before != PROFILE:
            cl.set_current_profile(PROFILE)
        cl.set_video_settings(a.fps, 1, iso_w, iso_h, iso_w, iso_h)
        for cat, key, val in [("Output", "Mode", "Simple"), ("SimpleOutput", "FilePath", a.folder),
                              ("SimpleOutput", "RecFormat2", "hybrid_mp4"), ("SimpleOutput", "RecEncoder", encoder),
                              ("SimpleOutput", "RecQuality", "HQ"), ("SimpleOutput", "RecTracks", "3")]:
            cl.set_profile_parameter(cat, key, val)  # RecTracks is a bitmask: 3 = tracks 1 + 2
    finally:
        if cl.get_profile_list().current_profile_name != before:
            cl.set_current_profile(before)

    # Sources from earlier versions of this setup. OBS only deletes an input once no scene uses it,
    # so take it out of every scene first.
    existing = {i["inputName"] for i in cl.get_input_list().inputs}
    stale = [n for n in OBSOLETE if n in existing]
    if stale:
        for scene in [s["sceneName"] for s in cl.get_scene_list().scenes]:
            for it in cl.get_scene_item_list(scene).scene_items:
                if it["sourceName"] in stale:
                    cl.remove_scene_item(scene, it["sceneItemId"])
        for name in stale:
            cl.remove_input(name)
            log(f"  removed old source '{name}'")
        time.sleep(1.0)

    def ensure_item(scene: str, name: str, kind: str, settings: dict) -> None:
        if name not in {i["inputName"] for i in cl.get_input_list().inputs}:
            cl.create_input(scene, name, kind, settings, True)
        else:
            try:
                cl.get_scene_item_id(scene, name)
            except obs.error.OBSSDKRequestError:
                cl.create_scene_item(scene, name, True)

    def wasapi_device(name_start: str) -> str | None:
        items = cl.get_input_properties_list_property_items(VOICE, "device_id").property_items
        hit = next((i for i in items if i["itemName"].lower().startswith(name_start.lower())), None)
        return hit["itemValue"] if hit else None

    cam_settings = {"deactivate_when_not_showing": True}
    made = []
    for scene, cam_name in SCENES.items():
        if cam_name == CAMS["Avatar"]:
            if not avatar:
                continue
            kind, settings = avatar[0], {**avatar[1], **cam_settings}
        else:
            kind, settings = "dshow_input", dict(cam_settings)
        if scene not in [s["sceneName"] for s in cl.get_scene_list().scenes]:
            cl.create_scene(scene)
        ensure_item(scene, SCREEN, "window_capture",
                    {"method": 2, "client_area": True, "cursor": True, "priority": 2})  # WGC: works for Chrome
        ensure_item(scene, cam_name, kind, settings)
        ensure_item(scene, VOICE, "wasapi_input_capture", {})
        ensure_item(scene, APP_AUDIO, "wasapi_process_output_capture", {"priority": 2})
        if cam_name == CAMS["Webcam"]:
            items = cl.get_input_properties_list_property_items(cam_name, "video_device_id").property_items
            match = next((i for i in items if a.webcam_match.lower() in i["itemName"].lower()), None)
            if match:  # webcams open at their default mode (often 640x480); ask for full HD
                cl.set_input_settings(cam_name, {"video_device_id": match["itemValue"], "res_type": 1,
                                                 "resolution": f"{cw}x{ch}", "fps_type": 1}, True)
            else:
                log(f"  WARNING: no camera matching '{a.webcam_match}' — double-click '{cam_name}' in OBS to pick it.")
        made.append(scene)

    dev = wasapi_device(rec["voice_device"]) if rec.get("voice_device") else "default"
    if dev:
        cl.set_input_settings(VOICE, {"device_id": dev}, True)
    else:
        log(f"  WARNING: no audio input starting with '{rec['voice_device']}' (brand.json recording.voice_device)")
    for name, track in ((VOICE, "1"), (APP_AUDIO, "2")):
        cl.set_input_audio_tracks(name, {str(t): str(t) == track for t in range(1, 7)})
    log(f"Ready: profile '{PROFILE}', scenes {', '.join(made)}. Lock Chrome's content area to "
        f"{rec['screen'][2]}x{rec['screen'][3]}, then: setup_obs.py --use --scene \"{made[0] if made else 'ISO Webcam'}\"")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=4455)
    rec = brand()["recording"]
    ap.add_argument("--avatar-source", default=rec.get("avatar_source"),
                    help="existing OBS source to copy the avatar camera from (brand.json recording.avatar_source)")
    ap.add_argument("--webcam-match", default=rec.get("webcam_match") or "",
                    help="text to find the webcam in OBS's device list (default: the first camera)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--folder", default=str(Path(os.path.expanduser(rec.get("recordings_folder") or "~/Videos/YouTube"))))
    ap.add_argument("--dry-run", action="store_true", help="print the plan without touching OBS")
    ap.add_argument("--use", action="store_true", help="switch OBS to a YouTube scene (see --scene)")
    ap.add_argument("--scene", help="with --use: ISO Avatar | ISO Webcam")
    ap.add_argument("--restore", action="store_true", help="back to the profile + scene + canvas active before --use")
    a = ap.parse_args()
    if a.use or a.restore:
        use(a)
    else:
        create(a)


if __name__ == "__main__":
    main()
