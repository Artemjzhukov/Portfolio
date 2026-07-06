import os
from dotenv import load_dotenv
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams
from langchain_community.embeddings import HuggingFaceEmbeddings

load_dotenv()

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "history_docs")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

def get_vector_store():
    """
    Возвращает QdrantVectorStore для работы с векторным хранилищем.
    Если подключение невозможно, выбрасывается исключение с понятным текстом.
    """
    try:
        # 1. Подключаемся к Qdrant
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        # Проверяем, что сервер доступен (лёгкий запрос)
        client.get_collections()
    except Exception as e:
        raise ConnectionError(
            f"Не удалось подключиться к Qdrant на {QDRANT_HOST}:{QDRANT_PORT}. "
            f"Убедитесь, что сервер запущен. Ошибка: {e}"
        )

    # 2. Проверяем наличие коллекции, при необходимости создаём
    collections = client.get_collections().collections
    if COLLECTION_NAME not in [c.name for c in collections]:
        # client.delete_collection(collection_name=COLLECTION_NAME)
        # print(f"old collection '{COLLECTION_NAME}' deleted")
        # Размерность эмбеддингов зависит от модели, укажите правильную
        # Для nomic-embed-text: 768, для all-minilm: 384, для llama3: 4096
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=384,  # измените под свою модель эмбеддингов
                distance=Distance.COSINE
            )
        )
        print(f"Коллекция '{COLLECTION_NAME}' создана.")

    # 3. Инициализируем эмбеддинги (через Ollama)
    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )

    # 4. Создаём хранилище
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding=embeddings
    )
    return vector_store

# Функция для добавления документов (опционально)
def add_documents_to_store(documents):
    vector_store = get_vector_store()
    vector_store.add_documents(documents)
    print(f"Добавлено {len(documents)} документов в '{COLLECTION_NAME}'.")