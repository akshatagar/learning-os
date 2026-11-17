"""The real wiring: local store, the configured capture source, the
pipeline, and the worker that runs them. Used by the CLI and the app."""
from reel_inbox.extractor.build import build_extractor
from reel_inbox.keys import get_secret
from reel_inbox.sources import SupabaseSource
from reel_inbox.store import make_store
from reel_inbox.worker import Worker


def configured_source():
    """The Supabase mailbox if both its URL and key are stored, else None."""
    url, key = get_secret("supabase-url"), get_secret("supabase-key")
    return SupabaseSource(url, key) if url and key else None


def make_worker(session_factory=None) -> Worker:
    return Worker(session_factory or make_store(), build_extractor, configured_source)
