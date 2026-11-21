import threading
import time
from pathlib import Path

import uvicorn

from web.serve import HOST, PORT, build_app, warm_embeddings

READY_POLL_SECONDS = 0.05

TITLE = "Learning OS"

# The taskbar and window icon (desktop/make_icon.py draws it).
ICON = Path(__file__).resolve().parent.parent / "desktop" / "learning-os.ico"

# Its own taskbar identity, so the window shows the Learning OS icon rather
# than grouping under python.exe with every other Python window.
APP_ID = "LearningOS.Desktop"
WIDTH = 1280
HEIGHT = 820

# The rail is fitted to the window height, so a short window shrinks the
# drawing rather than scrolling it. Past this floor the 11px stage labels
# stop being readable, so the window refuses to go smaller.
MIN_SIZE = (960, 640)

# --ground from web/static/tokens.css. Duplicated here because the window
# frame is painted before any stylesheet loads, and pywebview's default is
# white: without this every launch flashes white against the panel's ground.
BACKGROUND = "#0a0a0b"


def work_area() -> tuple[int, int] | None:
    """The usable desktop (screen minus taskbar) in logical pixels, or None.

    Read before pywebview starts, while this process is not yet DPI-aware, so
    Windows reports logical pixels - the unit pywebview's sizes are in.
    """
    try:
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        SPI_GETWORKAREA = 0x0030
        if not ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        ):
            return None
        return rect.right - rect.left, rect.bottom - rect.top
    except (AttributeError, OSError):
        # Not Windows, or the call is unavailable: keep the default size.
        return None


def fit_to(area: tuple[int, int] | None, size: tuple[int, int] = (WIDTH, HEIGHT),
           min_size: tuple[int, int] = MIN_SIZE) -> tuple[int, int]:
    """The opening window size: the default, shrunk to fit the work area,
    never below the minimum the rail can be drawn at."""
    if area is None:
        return size
    return tuple(
        max(low, min(want, room))
        for want, room, low in zip(size, area, min_size)
    )


class BackgroundServer:
    """uvicorn on its own thread, so a GUI can own the main one.

    pywebview's event loop must run on the main thread on both Windows and
    macOS, so the server cannot block there. The thread is a daemon: when the
    window closes and the process ends, nothing is left holding it open.
    """

    def __init__(self, app, host: str = HOST, port: int = PORT):
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._started = False
        self.url = f"http://{host}:{port}/"

    def start(self) -> None:
        self._started = True
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def wait_until_ready(self, timeout: float = 30.0) -> None:
        """Block until the socket is listening.

        The first call is slow - this is where sentence-transformers loads -
        so the timeout is generous.
        """
        if not self._started:
            raise RuntimeError("start() the server before waiting on it")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._server.started:
                return
            if not self._thread.is_alive():
                # Almost always a port conflict. Saying so beats a blank
                # window and a full timeout's wait.
                raise RuntimeError(
                    f"the server stopped before it was ready; is something "
                    f"else already listening on {self.url}?"
                )
            time.sleep(READY_POLL_SECONDS)

        raise TimeoutError(f"the server was not ready within {timeout}s")

    def stop(self, timeout: float = 5.0) -> None:
        self._server.should_exit = True
        self._thread.join(timeout)


_MARK = (
    '<svg viewBox="0 0 32 32" width="56" height="56" aria-hidden="true">'
    '<circle cx="7" cy="7" r="3" fill="none" stroke="#ededea" stroke-width="2.4"/>'
    '<circle cx="7" cy="25" r="3" fill="none" stroke="#ededea" stroke-width="2.4"/>'
    '<path d="M10 8.5 C15 11 16 14 19 16 M10 23.5 C15 21 16 18 19 16" fill="none" '
    'stroke="#ededea" stroke-width="2.4"/>'
    '<circle cx="23.5" cy="16" r="4.5" fill="#ff5a3c"/></svg>'
)


def _page(message: str, detail: str = "") -> str:
    """The screen shown while the server starts, or why it could not."""
    from html import escape

    extra = f'<p class="detail">{escape(detail)}</p>' if detail else ""
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"html,body{{height:100%;margin:0;background:{BACKGROUND};color:#ededea;"
        "font-family:'Segoe UI',sans-serif}"
        "main{height:100%;display:grid;place-content:center;justify-items:center;gap:18px}"
        "p{margin:0;font-size:15px;letter-spacing:.02em}"
        ".detail{max-width:60ch;color:rgba(237,237,234,.66);font-size:13px;text-align:center}"
        "</style></head><body><main>"
        f"{_MARK}<p>{escape(message)}</p>{extra}</main></body></html>"
    )


LOADING_HTML = _page("Starting Learning OS…")


def run(make_server, gui, title: str = TITLE, width: int = WIDTH,
        height: int = HEIGHT, min_size: tuple[int, int] = MIN_SIZE,
        icon: str | None = None, on_ready=None) -> None:
    """Open the window at once, then bring the server up behind it.

    The window appears on a loading screen the moment this is called, so a
    click on the taskbar answers immediately; the server (imports, database,
    embedding model) is built on pywebview's worker thread and the window
    switches to it once it is listening. Closing the window stops the server.

    make_server and gui are arguments so this can be tested without opening
    a window - the one thing a test cannot do.
    """
    window = gui.create_window(
        title, html=LOADING_HTML, width=width, height=height,
        background_color=BACKGROUND, min_size=min_size, maximized=True,
    )
    started = []

    def boot():
        try:
            server = make_server()
            started.append(server)
            server.start()
            server.wait_until_ready()
        except Exception as error:  # with no console, the window is the only place to say so
            window.load_html(_page("Learning OS could not start.", f"{type(error).__name__}: {error}"))
            return
        window.load_url(server.url)
        # Background work (the embedding model) starts only now: run while
        # the server starts, it competes for Python's import lock.
        if on_ready:
            on_ready()

    try:
        # Blocks on the main thread until the window closes; boot runs once
        # the window exists.
        if icon:
            gui.start(func=boot, icon=icon)
        else:
            gui.start(func=boot)
    finally:
        for server in started:
            server.stop()


def main() -> None:
    # Imported here, not at module scope, so the test suite never pulls in a
    # GUI toolkit to test wiring that is injected anyway.
    import webview

    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass  # not Windows: the default identity is fine

    built = []

    def make_server():
        # The slow part (imports, database, embedding model) happens here,
        # behind the loading screen rather than before the window exists.
        app = build_app()
        built.append(app)
        return BackgroundServer(app)

    width, height = fit_to(work_area())
    try:
        run(make_server, webview, width=width, height=height,
            icon=str(ICON) if ICON.is_file() else None, on_ready=warm_embeddings)
    finally:
        # A Reel Inbox run may be mid-pause between Instagram fetches; ask it
        # to stop rather than leave a fetch half done as the process exits.
        for app in built:
            app.state.reel_worker.stop()


if __name__ == "__main__":
    main()
