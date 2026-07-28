import threading
import time

import uvicorn

from web.serve import HOST, PORT

READY_POLL_SECONDS = 0.05


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
