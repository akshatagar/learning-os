import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

_EMBEDDING_FUNCTION = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")


def get_chroma_client(path):
    return chromadb.PersistentClient(path=str(path))


def get_concepts_collection(client):
    return client.get_or_create_collection(
        name="concepts",
        embedding_function=_EMBEDDING_FUNCTION,
        metadata={"hnsw:space": "cosine"},
    )
