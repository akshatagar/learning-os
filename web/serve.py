import uvicorn

from storage.db import get_engine
from web.app import create_app

DB_PATH = "data/learning_os.db"
HOST = "127.0.0.1"
PORT = 8765


def main() -> None:
    app = create_app(get_engine(DB_PATH))
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
