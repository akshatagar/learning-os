"""The /inbox HTTP surface. A host app mounts it with include_router; it
needs nothing from the host but a session factory."""
import webbrowser

from fastapi import APIRouter, HTTPException

from reel_inbox import reels
from reel_inbox.store import Capture


def make_router(session_factory, worker=None, open_url=webbrowser.open) -> APIRouter:
    router = APIRouter(prefix="/inbox")

    @router.get("")
    def state() -> dict:
        """Every undropped reel, newest first, with counts and worker status."""
        with session_factory() as session:
            return {
                "reels": reels.list_reels(session),
                "counts": reels.counts(session),
                "worker": worker.status() if worker else None,
            }

    @router.post("/reels/{capture_id}/drop")
    def drop(capture_id: str) -> dict:
        with session_factory() as session:
            try:
                reels.drop(session, capture_id)
            except LookupError:
                raise HTTPException(status_code=404, detail="no such reel")
        return {"ok": True}

    @router.post("/reels/{capture_id}/open")
    def open_reel(capture_id: str) -> dict:
        """The original reel, in the default browser, never the app window."""
        with session_factory() as session:
            capture = session.get(Capture, capture_id)
            if capture is None:
                raise HTTPException(status_code=404, detail="no such reel")
            url = reels.safe_web_url(capture.url)
        if url is None:
            raise HTTPException(status_code=400, detail="the reel link is not a web address")
        open_url(url)
        return {"opened": url}

    @router.post("/process")
    def process() -> dict:
        if worker is None:
            raise HTTPException(status_code=503, detail="processing is not available here")
        return {"started": worker.start(), **worker.status()}

    return router
