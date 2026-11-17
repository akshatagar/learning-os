import os
from pathlib import Path


def data_dir() -> Path:
    r"""Where Reel Inbox keeps models, caches and (later) its database.

    %APPDATA%\LearningOS on Windows, never the install or repo directory.
    """
    base = os.environ.get("APPDATA")
    root = Path(base) / "LearningOS" if base else Path.home() / ".learning-os"
    root.mkdir(parents=True, exist_ok=True)
    return root
