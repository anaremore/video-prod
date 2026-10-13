# video-prod

A local, free pipeline for editing YouTube videos with Claude Code. It's modeled on the "Claude Code + Parakeet + HyperFrames + FFmpeg" workflow, with OBS standing in for Tella and free or synthesized audio standing in for paid music libraries.

- **Editing a video, recording one, or changing graphics or brand:** use the `youtube-edit` skill (`.claude/skills/youtube-edit/SKILL.md`). It has the full workflow and the quality bar.
- **Run every step through the runner:** `.\vp <step> <slug>` (PowerShell) or `./vp.sh <step> <slug>` (Git Bash), from this folder. It finds Python itself (`VP_PYTHON`, `.venv`, or a conda env named `videoprod`). HyperFrames is pinned at 0.8.150 in `motion/`.
- **First run on a new machine:** `.\setup.ps1`, then `.\vp doctor`. Add `--obs` to `doctor` before recording.
- **Settings:** `brand/brand.default.json` ships the defaults; the user's own settings go in `brand/brand.json` (gitignored, deep-merged over the defaults). Personal or client themes go in `motion/themes/themes.local.json` (gitignored). Per-machine state lives in `local/` (gitignored). Machine-specific notes, if any, are in `CLAUDE.local.md`.
- **OBS:** the WebSocket server must be on; the scripts read its password from OBS's config. Never switch OBS scene collections from scripts (OBS can exit when plugins hold sources). The Source Record plugin was tested and dropped: it crashes or records the wrong source on OBS 32.
- **Editing defaults:**
  - **Gentle cuts.** Only pauses over 1 s and content cuts (retakes, tangents). Not the tight jump-cut style unless asked.
  - **Keep the intro and sign-off.** A creator's opening and closing lines are part of their format and are never cut. Only a flubbed retake inside them may go. `plan_cuts` enforces this.
  - **Themes.** One theme from `motion/themes/` restyles all graphics, captions and the camera ring. Pick it per video in `plan.json` `"style"`. `.\vp gallery` renders every template in every theme for choosing.
- **Media is large.** Don't copy recordings around; `new_video` hard-links them. `videos/*/work` can be deleted and regenerated.
- **This repo is public.** Never commit anything under `videos/`, recordings, `local/`, `brand/brand.json`, `themes.local.json`, `CLAUDE.local.md`, or rendered gallery sheets (they show real screens). `.gitignore` covers them; check `git status` before committing.
