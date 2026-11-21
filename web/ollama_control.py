"""Start and stop the local Ollama server, for the home page's buttons.

Most stages (summaries, drafts, matching, resolution) call Ollama, and on
this machine it is not started at login, so the app can start it: `ollama
serve` with no console window, left running when the app quits. Stop ends
Ollama outright, the tray app included, wherever it was started from.
"""
import os
import shutil
import subprocess
from pathlib import Path

import httpx

# The ollama client reads the same variable; this is its default.
HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
if "://" not in HOST:
    HOST = f"http://{HOST}"

# The Windows installer's default location, used when ollama is not on PATH
# (an app started from a shortcut may not see the user's PATH changes).
INSTALLED = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"


def is_running(get=httpx.get) -> bool:
    try:
        return get(f"{HOST}/api/version", timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


def find_ollama() -> str | None:
    return shutil.which("ollama") or (str(INSTALLED) if INSTALLED.is_file() else None)


def start(popen=subprocess.Popen, find=find_ollama) -> None:
    """Launch `ollama serve` in the background. Returns at once; the server
    takes a few seconds to answer."""
    exe = find()
    if exe is None:
        raise FileNotFoundError("ollama is not installed")
    popen([exe, "serve"],
          creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop(run=subprocess.run) -> None:
    """End every Ollama process: the tray app, the server and its model runners
    (all named ollama.exe). A name with no process is not an error."""
    for name in ("ollama app.exe", "ollama.exe"):
        run(["taskkill", "/IM", name, "/F", "/T"], capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
