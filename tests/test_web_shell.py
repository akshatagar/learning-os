import socket
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from web.shell import BackgroundServer


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


def test_the_server_serves_once_it_reports_ready():
    """wait_until_ready must mean it: the window opens the moment it returns.

    A window pointed at a socket that is not listening yet shows a browser
    error page, and nothing later repaints it.
    """
    server = BackgroundServer(_app(), port=_free_port())
    server.start()
    try:
        server.wait_until_ready()

        response = httpx.get(f"{server.url}health")
        assert response.json() == {"status": "ok"}
    finally:
        server.stop()


def test_stop_ends_the_thread():
    server = BackgroundServer(_app(), port=_free_port())
    server.start()
    server.wait_until_ready()

    server.stop()

    assert not server.is_alive()


def test_waiting_before_starting_is_a_programming_error():
    server = BackgroundServer(_app(), port=_free_port())

    with pytest.raises(RuntimeError, match="start"):
        server.wait_until_ready(timeout=0.1)


def test_a_server_that_dies_on_startup_fails_fast():
    """The alternative is hanging for the full timeout with a blank screen.

    A dead thread is the shape a port conflict takes - the most likely one
    being a browser server left running on the same port from 8a-1.
    """

    @asynccontextmanager
    async def lifespan(app):
        raise RuntimeError("startup exploded")
        yield

    server = BackgroundServer(FastAPI(lifespan=lifespan), port=_free_port())
    server.start()

    with pytest.raises(RuntimeError, match="stopped before it was ready"):
        server.wait_until_ready(timeout=10.0)
