"""Run the extractor over a list of URLs and report the referent-found rate.

Instagram access stays low and slow: a randomized pause before every
Instagram fetch after the first, and the run stops at the first rate-limit or
login-wall signal, leaving the rest unfetched.
"""
import random
import time
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from reel_inbox.extractor.pipeline import ExtractionFailed

STOP_REASONS = ("rate_limited", "login_wall")
NOT_RUN = "not_run_after_stop"


# The only query parameter that names content on these sites. Everything
# else in a shared link is tracking (utm_*, srtk, igsh, si, ...), which can
# identify the sharer and is never needed to fetch the reel.
_KEEP_PARAMS = {"v"}


def canonical_url(url: str) -> str:
    parts = urlparse(url.strip())
    kept = [(k, v) for k, v in parse_qsl(parts.query) if k in _KEEP_PARAMS]
    return urlunparse(parts._replace(query=urlencode(kept), fragment=""))


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\n")


def spreadsheet_safe(value):
    """A cell a spreadsheet will show as text, never run as a formula.
    Referents and captions come from the video, so they are untrusted.
    Leading whitespace is looked past: some spreadsheets trim it first."""
    if isinstance(value, str) and (value.startswith(_FORMULA_START)
                                   or value.lstrip().startswith(_FORMULA_START)):
        return "'" + value
    return value


def read_urls(path) -> list[str]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [canonical_url(line) for line in lines
            if line.strip() and not line.strip().startswith("#")]


def is_instagram(url: str) -> bool:
    return (urlparse(url).hostname or "").lower().endswith("instagram.com")


def _row(url, answer=None, reason=None, detail="", sources=()):
    answer = answer or {}
    return {
        "url": url,
        "referent": answer.get("referent"),
        "referent_type": answer.get("referent_type"),
        "search_query": answer.get("search_query"),
        "source_url_guess": answer.get("source_url_guess"),
        "confidence": answer.get("confidence"),
        "why_explorable": answer.get("why_explorable"),
        "failure_reason": reason,
        "detail": detail,
        "evidence": ", ".join(sources),
        "label": "",
    }


def run_eval(extractor, urls, delay=(20, 90), sleep=time.sleep,
             jitter=random.uniform, on_row=None) -> list[dict]:
    rows, stopped, fetched_instagram = [], False, False
    for url in urls:
        if stopped:
            row = _row(url, reason=NOT_RUN)
        else:
            if is_instagram(url):
                if fetched_instagram:
                    sleep(jitter(*delay))
                fetched_instagram = True
            try:
                answer = extractor.extract(url)
                row = _row(url, answer, sources=getattr(extractor, "last_evidence_sources", ()))
            except ExtractionFailed as failure:
                row = _row(url, reason=failure.reason, detail=failure.detail[:300],
                           sources=getattr(extractor, "last_evidence_sources", ()))
                stopped = failure.reason in STOP_REASONS
        rows.append(row)
        if on_row:
            on_row(row)
    return rows


def format_table(rows) -> str:
    lines = [
        "| url | referent | confidence | failure reason | label |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        confidence = "" if row["confidence"] is None else f"{row['confidence']:.2f}"
        lines.append(
            f"| {row['url']} | {row['referent'] or ''} | {confidence} "
            f"| {row['failure_reason'] or ''} |  |"
        )
    attempted = [r for r in rows if r["failure_reason"] != NOT_RUN]
    found = sum(1 for r in attempted if r["referent"])
    rate = f"{found / len(attempted):.0%}" if attempted else "n/a"
    lines += ["", f"referent found: {found}/{len(attempted)} ({rate})"]
    not_run = len(rows) - len(attempted)
    if not_run:
        lines.append(f"not run after a stop: {not_run}")
    reasons = Counter(r["failure_reason"] for r in attempted if r["failure_reason"])
    for reason, count in reasons.most_common():
        lines.append(f"  {reason}: {count}")
    return "\n".join(lines)
