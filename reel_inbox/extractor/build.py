import os

from reel_inbox.extractor.fetch import YtDlpFetcher
from reel_inbox.extractor.llm import OllamaSummary
from reel_inbox.extractor.pipeline import ReelExtractor
from reel_inbox.extractor.transcribe import WhisperTranscriber


def build_extractor(ocr: bool = False, cookies_file: str | None = None) -> ReelExtractor:
    """The real pipeline. Settings come from the environment (see
    .env.example); arguments win. Nothing heavy loads until first use."""
    browsers = [b.strip() for b in os.environ.get("REEL_COOKIE_BROWSERS", "firefox,chrome").split(",")
                if b.strip()]
    ocr = ocr or os.environ.get("REEL_OCR", "0") == "1"
    ocr_fn = None
    if ocr:
        from reel_inbox.extractor.frames import FrameOCR

        ocr_fn = FrameOCR()
    return ReelExtractor(
        fetcher=YtDlpFetcher(browsers, cookies_file or os.environ.get("REEL_COOKIES_FILE") or None),
        transcribe_fn=WhisperTranscriber(
            model=os.environ.get("REEL_WHISPER_MODEL", "small"),
            device=os.environ.get("REEL_WHISPER_DEVICE", "cpu"),
            compute_type=os.environ.get("REEL_WHISPER_COMPUTE", "int8"),
        ),
        llm_fn=OllamaSummary(os.environ.get("REEL_LLM_MODEL", "qwen3:8b")),
        ocr_fn=ocr_fn,
    )
