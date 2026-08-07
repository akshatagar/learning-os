from pathlib import Path

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parent.parent


def _cfg(db_path):
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def test_upgrade_creates_a_missing_parent_directory(tmp_path):
    """pytest creates tmp_path itself but never a subdirectory under it, so
    this stands in for a fresh clone: the real failure was a missing data/."""
    db_path = tmp_path / "nested" / "learning_os.db"

    command.upgrade(_cfg(db_path), "head")

    assert db_path.exists()
