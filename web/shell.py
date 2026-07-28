import threading
import time

import uvicorn

from storage.db import get_engine
from web.app import create_app
from web.serve import DB_PATH, HOST, PORT

READY_POLL_SECONDS = 0.05

TITLE = "learning-os"
WIDTH = 1280
HEIGHT = 820

# --ground from web/static/tokens.css. Duplicated here because the window
# frame is painted before any stylesheet loads, and pywebview's default is
# white: without this every launch flashes white against the panel's ground.
BACKGROUND = "#d7dcd3"


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


def run(server, gui, title: str = TITLE, width: int = WIDTH,
        height: int = HEIGHT) -> None:
    """Bind the server's life to the window's.

    Both are arguments rather than globals so this can be tested without
    opening a window - the one thing a test cannot do.
    """
    server.start()
    server.wait_until_ready()
    gui.create_window(
        title, server.url, width=width, height=height,
        background_color=BACKGROUND,
    )
    try:
        # Blocks on the main thread until the window closes.
        gui.start()
    finally:
        server.stop()


def main() -> None:
    # Imported here, not at module scope, so the test suite never pulls in a
    # GUI toolkit to test wiring that is injected anyway.
    import webview

    # Built before the window opens, which is where the startup pause lives:
    # sentence-transformers loads once here instead of per CLI invocation.
    server = BackgroundServer(create_app(get_engine(DB_PATH)))
    run(server, webview)


if __name__ == "__main__":
    main()
