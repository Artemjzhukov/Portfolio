import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Qdrant
from qdrant_client import QdrantClient

# load the .env file
load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "history_materials"

def get_vector_store():
    """Function to return a configured database object for searching"""
    
    # init embeddings
    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    
    # init Qdrant client
    client = QdrantClient(url=QDRANT_URL)
    
    # wrap in LangChain
    vector_store = Qdrant(
        client=client, 
        collection_name=COLLECTION_NAME, 
        embeddings=embeddings
    )
    return vector_store