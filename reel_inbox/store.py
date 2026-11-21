"""Reel Inbox's own tables, in its own SQLite file.

Kept apart from learning-os's database and migrations on purpose, so the
package can be lifted into its own repository unchanged. The local file is
the source of truth; the remote inbox is only a mailbox.
"""
from datetime import datetime

from sqlalchemy import ForeignKey, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from reel_inbox.paths import data_dir

# dropped is the only way a reel leaves the list; it is kept, not deleted.
STATUSES = ("pending", "ready", "failed", "dropped")


class Base(DeclarativeBase):
    pass


class Capture(Base):
    __tablename__ = "captures"

    # The remote row's id, so a capture pulled twice is stored once.
    id: Mapped[str] = mapped_column(primary_key=True)
    url: Mapped[str]
    source: Mapped[str]
    note: Mapped[str | None]
    captured_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(default="pending")
    # Set on the first failure while the item stays pending (one retry on
    # the next run); a second failure moves it to failed.
    fail_reason: Mapped[str | None]


class Extraction(Base):
    __tablename__ = "extractions"

    capture_id: Mapped[str] = mapped_column(ForeignKey("captures.id"), primary_key=True)
    # Only set when the reel was written up by hand (model "manual").
    title: Mapped[str | None]
    # Two or three sentences on what the reel says, written at processing,
    # or the hand-written description.
    summary: Mapped[str | None]
    model: Mapped[str | None]
    extracted_at: Mapped[datetime]


def default_url() -> str:
    return f"sqlite:///{data_dir() / 'reel_inbox.db'}"


def make_store(url: str | None = None):
    """A session factory over the Reel Inbox database, tables created.

    "sqlite://" gives an in-memory store shared across threads (tests).
    """
    url = url or default_url()
    if url == "sqlite://":
        engine = create_engine(url, connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
    else:
        # The worker thread and request threads each open their own session.
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _wal(connection, _):
            # Readers never wait on the worker's writes.
            connection.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _add_missing_columns(engine) -> None:
    """create_all never alters a table that already exists, and this store
    has no migrations, so a column added later is added here."""
    if "title" not in {c["name"] for c in inspect(engine).get_columns("extractions")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE extractions ADD COLUMN title VARCHAR"))
