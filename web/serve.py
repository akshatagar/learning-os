import uvicorn
from starlette.middleware.trustedhost import TrustedHostMiddleware

from storage.db import get_engine

DB_PATH = "data/learning_os.db"
CHROMA_PATH = "data/chroma"
HOST = "127.0.0.1"
PORT = 8765


def build_inbox():
    """Reel Inbox: its own store, its worker, and the /inbox router."""
    from reel_inbox.runtime import make_worker
    from reel_inbox.store import make_store
    from reel_inbox.web import make_router

    sessions = make_store()
    worker = make_worker(sessions)
    return make_router(sessions, worker=worker), worker


LOCAL_HOSTS = ["127.0.0.1", "localhost"]


def protect(app):
    """Answer only to local host names. A DNS-rebinding page reaches
    127.0.0.1 under its own name, and that name is what the Host header
    carries, so anything but these is refused before routing."""
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)
    return app


def build_app():
    """The one place the real stores are opened, shared by both entry points.

    Starting the app starts one Reel Inbox run in the background: pull new
    captures, then process a capped batch.

    The app and the vector store are imported here, not at module level, so
    the desktop shell can open its window before they load (seconds: the
    embedding model comes in with the vector store)."""
    from storage.vectors import get_chroma_client, get_concepts_collection
    from web.app import create_app

    collection = get_concepts_collection(get_chroma_client(CHROMA_PATH))
    router, worker = build_inbox()
    app = protect(create_app(get_engine(DB_PATH), collection, extra_routers=[router]))
    app.state.reel_worker = worker
    worker.start()
    return app


def main() -> None:
    uvicorn.run(build_app(), host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
