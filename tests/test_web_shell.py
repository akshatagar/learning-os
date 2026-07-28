import socket
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from web.shell import BackgroundServer, run


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


class FakeServer:
    # `log` lets a caller hand both fakes the same list, so their calls land
    # on one timeline and can be ordered against each other.
    def __init__(self, url="http://127.0.0.1:8765/", log=None):
        self.url = url
        self.calls = [] if log is None else log

    def start(self):
        self.calls.append("start")

    def wait_until_ready(self, timeout=30.0):
        self.calls.append("ready")

    def stop(self, timeout=5.0):
        self.calls.append("stop")


class FakeGui:
    def __init__(self, on_start=None, log=None):
        self.windows = []
        self.calls = [] if log is None else log
        self._on_start = on_start

    def create_window(self, title, url, **kwargs):
        self.calls.append("create_window")
        self.windows.append({"title": title, "url": url, **kwargs})

    def start(self):
        self.calls.append("gui_start")
        if self._on_start:
            self._on_start()


def test_the_window_opens_on_the_server_url():
    server, gui = FakeServer(), FakeGui()

    run(server, gui)

    assert gui.windows[0]["url"] == server.url


def test_the_server_is_ready_before_the_window_is_created():
    """Ordering is the whole risk. A window created first shows an error page."""
    timeline = []
    server, gui = FakeServer(log=timeline), FakeGui(log=timeline)

    run(server, gui)

    assert timeline.index("ready") < timeline.index("create_window")


def test_closing_the_window_stops_the_server():
    """gui.start() returns when the window closes - that is the shutdown signal."""
    server, gui = FakeServer(), FakeGui()

    run(server, gui)

    assert server.calls == ["start", "ready", "stop"]


def test_the_server_stops_even_if_the_gui_raises():
    """Otherwise a GUI crash leaves a server bound to the port forever."""
    def explode():
        raise RuntimeError("gui exploded")

    server, gui = FakeServer(), FakeGui(on_start=explode)

    with pytest.raises(RuntimeError, match="gui exploded"):
        run(server, gui)

    assert "stop" in server.calls
