"""Keys live in Windows Credential Manager (via keyring), never in files.

Environment variables are read as a fallback for development and CI only.
"""
import os

SERVICE = "LearningOS"

# name -> environment fallback
NAMES = {
    "supabase-url": "REEL_SUPABASE_URL",
    "supabase-key": "REEL_SUPABASE_KEY",
}


def get_secret(name: str) -> str | None:
    if name not in NAMES:
        raise KeyError(name)
    try:
        import keyring

        value = keyring.get_password(SERVICE, name)
    except Exception:
        value = None
    return value or os.environ.get(NAMES[name]) or None


def set_secret(name: str, value: str) -> None:
    if name not in NAMES:
        raise KeyError(name)
    import keyring

    keyring.set_password(SERVICE, name, value)
