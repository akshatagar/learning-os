from tempfile import TemporaryDirectory

from reel_inbox.extractor.fetch import FetchFailed
from reel_inbox.extractor.llm import build_evidence
from reel_inbox.extractor.schema import normalize


class ExtractionFailed(Exception):
    """reason is a short code: login_wall, rate_limited, unavailable,
    fetch_error, no_evidence, llm_error, no_referent."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class ReelExtractor:
    """fetch -> captions, else transcribe -> optional OCR -> one model call."""

    def __init__(self, fetcher, transcribe_fn, llm_fn, ocr_fn=None):
        self.fetcher = fetcher
        self.transcribe_fn = transcribe_fn
        self.llm_fn = llm_fn
        self.ocr_fn = ocr_fn
        # Which evidence the last call had, for the eval report.
        self.last_evidence_sources: list[str] = []

    def extract(self, url: str) -> dict:
        sources: list[str] = []
        self.last_evidence_sources = sources
        with TemporaryDirectory() as tmp:
            try:
                fetched = self.fetcher.fetch(
                    url, tmp, "always" if self.ocr_fn else "if_no_captions",
                )
            except FetchFailed as error:
                raise ExtractionFailed(error.reason, error.detail) from error

            spoken = fetched.captions
            if spoken:
                sources.append("captions")
            elif fetched.media_path:
                try:
                    spoken = self.transcribe_fn(fetched.media_path)
                except Exception as error:  # one broken file must not end a run
                    spoken = None
                    sources.append(f"transcribe failed ({type(error).__name__})")
                if spoken:
                    sources.append("whisper")

            on_screen = None
            frames_from = fetched.video_path or fetched.media_path
            if self.ocr_fn and frames_from:
                try:
                    on_screen = self.ocr_fn(frames_from)
                except Exception as error:
                    sources.append(f"ocr failed ({type(error).__name__})")
                if on_screen:
                    sources.append("ocr")

        if fetched.meta.get("description"):
            sources.append("caption text")
        evidence = build_evidence(fetched.meta, spoken, on_screen)
        if evidence is None:
            raise ExtractionFailed("no_evidence", "no title, caption, speech or on-screen text")

        try:
            answer = normalize(self.llm_fn(evidence))
        except Exception as error:
            raise ExtractionFailed("llm_error", f"{type(error).__name__}: {error}") from error
        if answer["referent"] is None:
            raise ExtractionFailed("no_referent", answer.get("why_explorable") or "")
        return answer
