"""Starts Learning OS with no console window.

Run by the base interpreter's pythonw.exe (see make_shortcut.ps1), not the
one in .venv\\Scripts: uv's venv launchers are console programs, even the one
named pythonw.exe, so going through them opens a terminal behind the app.
This file loads the project's .venv packages itself and then runs the
desktop shell, exactly as `python -m web.shell` would.
"""
import os
import runpy
import site
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

os.chdir(ROOT)  # data/ and the static files are found relative to here
sys.path.insert(0, str(ROOT))
# addsitedir, not a bare sys.path entry: it also runs the .pth files that
# packages such as pywin32 rely on.
site.addsitedir(str(ROOT / ".venv" / "Lib" / "site-packages"))

runpy.run_module("web.shell", run_name="__main__")
