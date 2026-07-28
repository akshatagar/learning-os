import uvicorn

from storage.db import get_engine
from storage.vectors import get_chroma_client, get_concepts_collection
from web.app import create_app

DB_PATH = "data/learning_os.db"
CHROMA_PATH = "data/chroma"
HOST = "127.0.0.1"
PORT = 8765


def build_app():
    """The one place the real stores are opened, shared by both entry points."""
    collection = get_concepts_collection(get_chroma_client(CHROMA_PATH))
    return create_app(get_engine(DB_PATH), collection)


def main() -> None:
    uvicorn.run(build_app(), host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
