"""One background run at a time: pull new captures, then process a capped
batch. Started on app launch and by "Process now"; stopped by Quit."""
import logging
import threading
from dataclasses import asdict

from reel_inbox.queue import DEFAULT_DELAY, DEFAULT_LIMIT, RunReport, process_pending
from reel_inbox.sources import import_captures

log = logging.getLogger("reel_inbox")


class Worker:
    def __init__(self, session_factory, extractor_factory, source_factory=lambda: None,
                 limit: int = DEFAULT_LIMIT, delay=DEFAULT_DELAY):
        """extractor_factory and source_factory are called once per run, so
        a key added after launch is picked up by the next run. A source
        factory returning None means no remote inbox is configured."""
        self.sessions = session_factory
        self.extractor_factory = extractor_factory
        self.source_factory = source_factory
        self.limit, self.delay = limit, delay
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_report: RunReport | None = None
        self.last_pulled: int | None = None
        self.last_error: str | None = None
        # The reel being extracted right now: it cannot be dropped or written up.
        self.current: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Begin a run in the background. False if one is already going."""
        with self._lock:
            if self.running:
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="reel-inbox", daemon=True)
            self._thread.start()
            return True

    def stop(self, timeout: float = 10.0) -> None:
        """Ask the run to end between items (or mid-pause) and wait for it."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _run(self) -> None:
        self.last_error = None
        try:
            source = self.source_factory()
            if source is not None:
                self.last_pulled = import_captures(self.sessions, source)
        except Exception as error:  # an unreachable inbox must not block processing
            self.last_error = f"pull failed: {type(error).__name__}: {error}"
            log.warning(self.last_error)
        try:
            self.last_report = process_pending(
                self.sessions, self.extractor_factory(), limit=self.limit, delay=self.delay,
                # Waiting on the event, not time.sleep, so Quit interrupts a pause.
                sleep=self._stop.wait, should_stop=self._stop.is_set,
                on_item=self._set_current,
            )
        except Exception as error:
            self.last_error = f"processing failed: {type(error).__name__}: {error}"
            log.exception("reel inbox run failed")
        finally:
            self.current = None

    def _set_current(self, capture_id: str | None) -> None:
        self.current = capture_id

    def status(self) -> dict:
        return {
            "running": self.running,
            "current": self.current,
            "last_pulled": self.last_pulled,
            "last_report": asdict(self.last_report) if self.last_report else None,
            "last_error": self.last_error,
        }
