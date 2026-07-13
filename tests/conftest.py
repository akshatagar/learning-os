from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from storage.db import get_engine, get_session
from storage.vectors import get_chroma_client, get_concepts_collection

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_migrations(db_path):
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / "learning_os.db"
    _run_migrations(db_path)
    return get_engine(db_path)


@pytest.fixture
def session(engine):
    with get_session(engine) as session:
        yield session


@pytest.fixture
def collection(tmp_path):
    client = get_chroma_client(tmp_path / "chroma")
    return get_concepts_collection(client)
