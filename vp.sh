#!/usr/bin/env bash
# youtube-edit runner (Git Bash):  ./vp.sh <step> <slug> [options]   e.g.  ./vp.sh transcribe my-video
# Python: $VP_PYTHON > .venv (made by setup.ps1) > conda env "videoprod" > python on PATH.
here="$(cd "$(dirname "$0")" && pwd)"
py="$VP_PYTHON"
for c in "$here/.venv/Scripts/python.exe" "$here/.venv/bin/python" \
         "$HOME/miniforge3/envs/videoprod/python.exe" "$HOME/miniconda3/envs/videoprod/python.exe"; do
  [ -z "$py" ] && [ -x "$c" ] && py="$c"
done
py="${py:-python}"
if [ -z "$1" ]; then ls "$here/.claude/skills/youtube-edit/scripts" | grep '\.py$' | grep -vE 'common|winutil|sync' | sed 's/\.py$//'; exit 1; fi
step="$1"; shift
exec "$py" "$here/.claude/skills/youtube-edit/scripts/$step.py" "$@"
