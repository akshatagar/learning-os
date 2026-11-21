"""python -m reel_inbox extract <url> | eval <file> | set-secret <name> | pull | process"""
import argparse
import csv
import getpass
import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

from reel_inbox.eval import format_table, read_urls, run_eval, spreadsheet_safe
from reel_inbox.extractor.build import build_extractor
from reel_inbox.extractor.pipeline import ExtractionFailed
from reel_inbox.keys import NAMES, set_secret
from reel_inbox.paths import data_dir
from reel_inbox.runtime import configured_source, make_worker
from reel_inbox.sources import import_captures
from reel_inbox.store import make_store


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="python -m reel_inbox")
    sub = parser.add_subparsers(dest="command", required=True)

    one = sub.add_parser("extract", help="summarize one reel")
    one.add_argument("url")

    many = sub.add_parser("eval", help="run extract over a file of URLs and print a table")
    many.add_argument("file")
    many.add_argument("--delay-min", type=float, default=20)
    many.add_argument("--delay-max", type=float, default=90)
    many.add_argument("--out", help="CSV to write (default: under %%APPDATA%%\\LearningOS\\eval)")

    for p in (one, many):
        p.add_argument("--ocr", action="store_true", help="also OCR a few frames")
        p.add_argument("--cookies", help="path to a cookies.txt (Netscape format)")

    secret = sub.add_parser("set-secret", help="store a key in Windows Credential Manager")
    secret.add_argument("name", choices=sorted(NAMES))
    sub.add_parser("pull", help="copy waiting captures from the remote inbox")
    sub.add_parser("process", help="process one capped batch of stored pending captures (no pull)")
    args = parser.parse_args(argv)

    if args.command == "set-secret":
        # Prompted, never an argument: arguments land in shell history.
        set_secret(args.name, getpass.getpass(f"{args.name}: ").strip())
        print(f"stored {args.name} in Windows Credential Manager")
        return 0
    if args.command == "pull":
        source = configured_source()
        if source is None:
            print("no inbox configured: run set-secret for supabase-url and supabase-key")
            return 1
        print(f"pulled {import_captures(make_store(), source)} new capture(s)")
        return 0
    if args.command == "process":
        worker = make_worker()
        worker.start()
        worker.join()
        print(json.dumps(worker.status(), indent=2))
        return 0 if worker.status()["last_error"] is None else 1

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
        status = (row["summary"] or "")[:60] or row["failure_reason"]
        print(f"[{progress.n}/{len(urls)}] {row['url']} -> {status}", file=sys.stderr, flush=True)
        progress.n += 1
    progress.n = 1

    rows = run_eval(extractor, urls, delay=(args.delay_min, args.delay_max), on_row=progress)
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["url"])
        writer.writeheader()
        writer.writerows({k: spreadsheet_safe(v) for k, v in row.items()} for row in rows)
    print(format_table(rows))
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
