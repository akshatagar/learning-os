import socket
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from web.shell import BACKGROUND, HEIGHT, MIN_SIZE, WIDTH, BackgroundServer, fit_to, run


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
    # `log` lets a caller hand the fakes the same list, so their calls land
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


class FakeWindow:
    def __init__(self, log):
        self.calls = log
        self.urls, self.pages = [], []

    def load_url(self, url):
        self.calls.append("load_url")
        self.urls.append(url)

    def load_html(self, html):
        self.calls.append("load_html")
        self.pages.append(html)


class FakeGui:
    """pywebview's surface, as run() uses it: start(func) runs func once the
    window exists, then blocks until the window closes."""

    def __init__(self, on_start=None, log=None):
        self.windows = []
        self.calls = [] if log is None else log
        self._on_start = on_start
        self.window = FakeWindow(self.calls)

    def create_window(self, title, url=None, **kwargs):
        self.calls.append("create_window")
        self.windows.append({"title": title, "url": url, **kwargs})
        return self.window

    def start(self, func=None, **kwargs):
        self.calls.append("gui_start")
        self.start_kwargs = kwargs
        if func:
            func()
        if self._on_start:
            self._on_start()


def test_the_window_carries_the_app_icon_when_one_is_given():
    server, gui = FakeServer(), FakeGui()

    run(lambda: server, gui, icon="learning-os.ico")

    assert gui.start_kwargs == {"icon": "learning-os.ico"}


def test_the_icon_file_ships_with_the_repo():
    from web.shell import ICON

    assert ICON.is_file() and ICON.suffix == ".ico"


def test_the_window_opens_at_once_on_a_loading_screen():
    """Startup takes seconds (imports, the embedding model). The window comes
    up before any of it, so a click on the taskbar answers immediately."""
    timeline = []
    server, gui = FakeServer(log=timeline), FakeGui(log=timeline)

    run(lambda: server, gui)

    assert gui.windows[0]["url"] is None
    assert "Starting Learning OS" in gui.windows[0]["html"]
    assert timeline.index("create_window") < timeline.index("start")


def test_the_app_loads_only_once_the_server_is_ready():
    """A window pointed at a socket that is not listening shows an error page."""
    timeline = []
    server, gui = FakeServer(log=timeline), FakeGui(log=timeline)

    run(lambda: server, gui)

    assert gui.window.urls == [server.url]
    assert timeline.index("ready") < timeline.index("load_url")


def test_the_window_opens_maximized_in_the_panel_ground_colour():
    server, gui = FakeServer(), FakeGui()

    run(lambda: server, gui)

    assert gui.windows[0]["maximized"] is True
    assert gui.windows[0]["background_color"] == BACKGROUND


def test_a_server_that_cannot_start_is_reported_in_the_window():
    """With no console, an exception nobody shows is a window stuck on
    'Starting' forever."""
    def broken():
        raise RuntimeError("port 8765 is taken")

    gui = FakeGui()

    run(broken, gui)

    assert gui.window.urls == []
    assert "port 8765 is taken" in gui.window.pages[0]


def test_closing_the_window_stops_the_server():
    """gui.start() returns when the window closes - that is the shutdown signal."""
    server, gui = FakeServer(), FakeGui()

    run(lambda: server, gui)

    assert server.calls == ["start", "ready", "stop"]


def test_the_server_stops_even_if_the_gui_raises():
    """Otherwise a GUI crash leaves a server bound to the port forever."""
    def explode():
        raise RuntimeError("gui exploded")

    server, gui = FakeServer(), FakeGui(on_start=explode)

    with pytest.raises(RuntimeError, match="gui exploded"):
        run(lambda: server, gui)

    assert "stop" in server.calls


def test_the_window_cannot_be_shrunk_below_its_minimum():
    server, gui = FakeServer(), FakeGui()

    run(lambda: server, gui)

    assert gui.windows[0]["min_size"] == MIN_SIZE


def test_the_window_opens_at_full_size_when_the_screen_has_room():
    assert fit_to((1920, 1040)) == (WIDTH, HEIGHT)


def test_the_window_opens_no_larger_than_the_work_area():
    """1920x1080 at 150% scaling leaves a 1280x672 logical work area. The
    window used to open at 820 tall and put its bottom edge off-screen."""
    assert fit_to((1280, 672)) == (1280, 672)


def test_the_window_never_opens_below_its_minimum():
    assert fit_to((800, 500)) == MIN_SIZE


def test_an_unknown_work_area_keeps_the_default_size():
    assert fit_to(None) == (WIDTH, HEIGHT)


def test_background_work_starts_only_after_the_app_is_showing():
    """Warming the embedding model while the server starts slowed the start
    to a crawl (both wait on Python's import lock), so it comes after."""
    timeline = []
    server, gui = FakeServer(log=timeline), FakeGui(log=timeline)

    run(lambda: server, gui, on_ready=lambda: timeline.append("warm"))

    assert timeline.index("load_url") < timeline.index("warm")
