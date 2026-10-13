@echo off
rem youtube-edit runner:  vp <step> <slug> [options]   e.g.  vp transcribe my-video
rem Steps are the scripts in .claude\skills\youtube-edit\scripts (doctor, new_video, transcribe, plan_cuts, cut,
rem snapshots, research, graphics, layout, captions, finish, gallery, make_sfx, setup_obs, record).
rem Python: %VP_PYTHON% > .venv (made by setup.ps1) > conda env "videoprod" > python on PATH.
setlocal
if not "%VP_PYTHON%"=="" goto run
if exist "%~dp0.venv\Scripts\python.exe" ( set "VP_PYTHON=%~dp0.venv\Scripts\python.exe" & goto run )
if exist "%USERPROFILE%\miniforge3\envs\videoprod\python.exe" ( set "VP_PYTHON=%USERPROFILE%\miniforge3\envs\videoprod\python.exe" & goto run )
if exist "%USERPROFILE%\miniconda3\envs\videoprod\python.exe" ( set "VP_PYTHON=%USERPROFILE%\miniconda3\envs\videoprod\python.exe" & goto run )
set "VP_PYTHON=python"
:run
if "%~1"=="" (
  dir /b "%~dp0.claude\skills\youtube-edit\scripts\*.py" | findstr /v /i "common.py winutil.py sync.py"
  exit /b 1
)
"%VP_PYTHON%" "%~dp0.claude\skills\youtube-edit\scripts\%~1.py" %2 %3 %4 %5 %6 %7 %8 %9
