import threading

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

MODEL_NAME = "all-MiniLM-L6-v2"


class LazySentenceTransformer(SentenceTransformerEmbeddingFunction):
    """Chroma's SentenceTransformer embedding function, minus the wait.

    The parent loads sentence_transformers (and PyTorch under it, about ten
    seconds) in its constructor. This one defers that to the first call, so
    the app can start listening first. Name and config are inherited
    unchanged, which is what Chroma checks against the collection on disk.
    """

    def __init__(self, model_name: str = MODEL_NAME, device: str = "cpu",
                 normalize_embeddings: bool = False, **kwargs):
        self.model_name = model_name
        self.device = device
        self.normalize_embeddings = normalize_embeddings
        self.kwargs = kwargs
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        """Load the model now. Safe to call from any thread, any number of
        times; the first caller pays and the rest wait for it."""
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                if self.model_name not in self.models:
                    self.models[self.model_name] = SentenceTransformer(
                        model_name_or_path=self.model_name, device=self.device, **self.kwargs,
                    )
                self._model = self.models[self.model_name]

    def __call__(self, input):
        self.load()
        return super().__call__(input)

    @staticmethod
    def build_from_config(config):
        # Chroma rebuilds the function from its config when a collection
        # opens (to check it is not a legacy one). The inherited version
        # builds the eager parent and loads the model; this one stays lazy.
        return LazySentenceTransformer(
            model_name=config["model_name"],
            device=config["device"],
            normalize_embeddings=config["normalize_embeddings"],
            **config.get("kwargs", {}),
        )


EMBEDDING_FUNCTION = LazySentenceTransformer()


def get_chroma_client(path):
    return chromadb.PersistentClient(path=str(path))


def get_concepts_collection(client):
    return client.get_or_create_collection(
        name="concepts",
        embedding_function=EMBEDDING_FUNCTION,
        metadata={"hnsw:space": "cosine"},
    )
