"""What importing the app pulls in, checked in a fresh interpreter.

Startup time is mostly imports. Docling alone cost about 19 seconds at every
launch while being needed only to ingest a PDF, and anything web.shell
imports runs before the window can appear.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _loaded_after(statement: str, modules: list[str]) -> list[str]:
    code = (
        f"import sys; {statement}; "
        f"print(','.join(m for m in {modules!r} if m in sys.modules))"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr[-2000:]
    return [m for m in result.stdout.strip().split(",") if m]


def test_the_app_does_not_load_the_pdf_parser_until_a_paper_is_ingested():
    assert _loaded_after("import web.app", ["docling", "torch"]) == []


def test_the_window_can_open_before_the_heavy_libraries_load():
    heavy = ["chromadb", "sentence_transformers", "torch", "docling", "web.app"]
    assert _loaded_after("import web.shell", heavy) == []
