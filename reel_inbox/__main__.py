"""python -m reel_inbox extract <url> | eval <file>"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

from reel_inbox.eval import format_table, read_urls, run_eval
from reel_inbox.extractor.fetch import YtDlpFetcher
from reel_inbox.extractor.llm import OllamaReferent
from reel_inbox.extractor.pipeline import ExtractionFailed, ReelExtractor
from reel_inbox.extractor.transcribe import WhisperTranscriber
from reel_inbox.paths import data_dir


def build_extractor(ocr: bool, cookies_file: str | None) -> ReelExtractor:
    """Settings come from the environment (see .env.example), flags win."""
    browsers = [b.strip() for b in os.environ.get("REEL_COOKIE_BROWSERS", "firefox,chrome").split(",") if b.strip()]
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
        llm_fn=OllamaReferent(os.environ.get("REEL_LLM_MODEL", "qwen3:8b")),
        ocr_fn=ocr_fn,
    )


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="python -m reel_inbox")
    sub = parser.add_subparsers(dest="command", required=True)

    one = sub.add_parser("extract", help="extract the referent of one reel")
    one.add_argument("url")

    many = sub.add_parser("eval", help="run extract over a file of URLs and print a table")
    many.add_argument("file")
    many.add_argument("--delay-min", type=float, default=20)
    many.add_argument("--delay-max", type=float, default=90)
    many.add_argument("--out", help="CSV to write (default: under %%APPDATA%%\\LearningOS\\eval)")

    for p in (one, many):
        p.add_argument("--ocr", action="store_true", help="also OCR a few frames")
        p.add_argument("--cookies", help="path to a cookies.txt (Netscape format)")
    args = parser.parse_args(argv)

    extractor = build_extractor(args.ocr, args.cookies)

    if args.command == "extract":
        try:
            print(json.dumps(extractor.extract(args.url), indent=2, ensure_ascii=False))
        except ExtractionFailed as failure:
            print(json.dumps({"failure_reason": failure.reason, "detail": failure.detail}, indent=2))
            return 1
        finally:
            print(f"cookies: {extractor.fetcher.last_cookie_source or 'none'}; "
                  f"evidence: {', '.join(extractor.last_evidence_sources) or 'none'}",
                  file=sys.stderr)
        return 0

    urls = read_urls(args.file)
    out = args.out or str(data_dir() / "eval" / f"eval-{datetime.now():%Y%m%d-%H%M%S}.csv")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    def progress(row):
        status = row["referent"] or row["failure_reason"]
        print(f"[{progress.n}/{len(urls)}] {row['url']} -> {status}", file=sys.stderr, flush=True)
        progress.n += 1
    progress.n = 1

    rows = run_eval(extractor, urls, delay=(args.delay_min, args.delay_max), on_row=progress)
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["url"])
        writer.writeheader()
        writer.writerows(rows)
    print(format_table(rows))
    print(f"\nwritten: {out} (fill in the label column)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
