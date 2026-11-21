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


def test_the_vector_store_opens_without_loading_the_embedding_model():
    """sentence_transformers brings PyTorch: about ten seconds. The server
    can listen without it; the model loads in the background after."""
    assert _loaded_after("import storage.vectors", ["sentence_transformers", "torch"]) == []


def test_the_lazy_embedding_function_keeps_chromas_identity():
    """The collection on disk records which embedding function made it; a
    different name or config would be refused when the collection opens."""
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    from storage.vectors import EMBEDDING_FUNCTION

    assert isinstance(EMBEDDING_FUNCTION, SentenceTransformerEmbeddingFunction)
    assert EMBEDDING_FUNCTION.name() == SentenceTransformerEmbeddingFunction.name()
    assert EMBEDDING_FUNCTION.get_config()["model_name"] == "all-MiniLM-L6-v2"


def test_opening_the_collection_does_not_load_the_embedding_model(tmp_path):
    """Chroma rebuilds the embedding function from its config when a
    collection opens; that rebuild must stay lazy too."""
    code = (
        "from storage.vectors import get_chroma_client, get_concepts_collection; "
        f"get_concepts_collection(get_chroma_client(r'{tmp_path}'))"
    )
    assert _loaded_after(code, ["sentence_transformers", "torch"]) == []
