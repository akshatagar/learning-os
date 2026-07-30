import queue
import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Job:
    id: str
    kind: str
    status: str = "running"
    error: str | None = None
    # Monotonic: this measures a duration and must not move if the system
    # clock does.
    started_at: float = field(default_factory=time.monotonic)
    thread: threading.Thread | None = field(default=None, repr=False)


class JobRegistry:
    """Tracks background work and broadcasts its transitions.

    Jobs are deliberately not persisted. If the process dies mid-run the
    record vanishes, which is correct: every underlying stage selects rows by
    "not yet handled" and commits per row, so re-running continues from where
    it stopped.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._jobs: dict[str, Job] = {}
        self._by_kind: dict[str, Job] = {}
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def running_kinds(self) -> set[str]:
        with self._lock:
            return set(self._by_kind)

    def running_jobs(self) -> list[Job]:
        with self._lock:
            return list(self._by_kind.values())

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def subscribe(self) -> queue.Queue:
        stream: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(stream)
        return stream

    def unsubscribe(self, stream: queue.Queue) -> None:
        with self._lock:
            if stream in self._subscribers:
                self._subscribers.remove(stream)

    def publish(self, event: dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for stream in subscribers:
            stream.put(event)

    def start(self, kind: str, fn) -> Job:
        with self._lock:
            existing = self._by_kind.get(kind)
            if existing is not None:
                return existing
            job = Job(id=str(uuid.uuid4()), kind=kind)
            self._jobs[job.id] = job
            self._by_kind[kind] = job

        job.thread = threading.Thread(
            target=self._run, args=(job, fn), daemon=True
        )
        # Published before the thread starts. A fast job can finish and publish
        # "done" the instant it is running, and subscribers must never see a
        # completion before the start that caused it.
        self.publish(
            {"type": "job", "id": job.id, "kind": kind, "status": "running"}
        )
        job.thread.start()
        return job

    def _run(self, job: Job, fn) -> None:
        # This thread's own session, opened here and closed here. A Session is
        # not thread-safe, and nothing loaded from it may leave this frame.
        session = self._session_factory()
        try:
            fn(session)
            job.status = "done"
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
        finally:
            session.close()
            with self._lock:
                if self._by_kind.get(job.kind) is job:
                    del self._by_kind[job.kind]
            self.publish(
                {
                    "type": "job",
                    "id": job.id,
                    "kind": job.kind,
                    "status": job.status,
                }
            )
