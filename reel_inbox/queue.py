"""The background processing run: pending captures in, extractions out.

Low and slow by construction: a capped number of items per run, a random
pause before every Instagram fetch after the first, and the run ends at the
first rate-limit or login-wall signal with the rest left pending.
"""
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from reel_inbox.eval import STOP_REASONS, is_instagram
from reel_inbox.extractor.pipeline import ExtractionFailed
from reel_inbox.store import Capture, Extraction

DEFAULT_LIMIT = 8
DEFAULT_DELAY = (20.0, 90.0)


@dataclass
class RunReport:
    processed: int = 0
    failed: int = 0
    retry_next_run: int = 0
    stopped: str | None = None


def process_pending(session_factory, extractor, limit: int = DEFAULT_LIMIT,
                    delay=DEFAULT_DELAY, sleep=time.sleep, jitter=random.uniform,
                    should_stop=lambda: False, now=lambda: datetime.now(timezone.utc)) -> RunReport:
    """One run over a snapshot of the oldest pending captures.

    A failure is never retried within the run. The first failure keeps the
    item pending with its reason (so the next run tries once more); the
    second moves it to failed for good.
    """
    report = RunReport()
    with session_factory() as session:
        ids = session.scalars(
            select(Capture.id).where(Capture.status == "pending")
            .order_by(Capture.captured_at).limit(limit)
        ).all()

    fetched_instagram = False
    for capture_id in ids:
        if should_stop():
            report.stopped = "stop_requested"
            break
        with session_factory() as session:
            capture = session.get(Capture, capture_id)
            if is_instagram(capture.url):
                if fetched_instagram:
                    sleep(jitter(*delay))
                    if should_stop():
                        report.stopped = "stop_requested"
                        break
                fetched_instagram = True
            try:
                answer = extractor.extract(capture.url)
            except ExtractionFailed as failure:
                if failure.reason in STOP_REASONS:
                    # Not the item's fault: leave it as it was and stop.
                    report.stopped = failure.reason
                    break
                if capture.fail_reason is None:
                    capture.fail_reason = failure.reason
                    report.retry_next_run += 1
                else:
                    capture.status, capture.fail_reason = "failed", failure.reason
                    report.failed += 1
                session.commit()
                continue

            session.merge(Extraction(
                capture_id=capture.id, summary=answer["summary"],
                model=getattr(extractor, "model", None), extracted_at=now(),
            ))
            capture.status, capture.fail_reason = "ready", None
            session.commit()
            report.processed += 1
    return report
