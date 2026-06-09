import os
from dotenv import load_dotenv
from langchain_community.llms import Ollama
from langchain.chains import RetrievalQA
from core.database import get_vector_store

# load environment variables from .env file (like OLLAMA_URL)
load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

def create_history_assistant():
    """Function to create and initialize the AI assistant chain."""
    print("Initializing the AI assistant model...")
    
    # 1. Connect to Ollama (which will be running on the Mac)
    llm = Ollama(
        base_url=OLLAMA_URL,
        model="llama3:8b",
        temperature=0.3 # Lower temperature means more focused and deterministic answers, which is good for fact-based Q&A
    )
    
    # 2. retrieve the vector store (which contains the indexed documents from your history)
    vector_store = get_vector_store()
    
    # transform the vector store into a retriever, which will be used to find relevant documents based on the user's question
    # search_kwargs={"k": 3} means that the system will find the 3 most similar documents
    retriever = vector_store.as_retriever(search_kwargs={"k": 3})
    
    # 3. create the final RAG chain
    print("Creating the LangChain for retrieval and verification...")
    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff", # Basic chain type that simply stuffs all retrieved documents into the prompt. For more complex logic, you can explore other chain types.
        retriever=retriever,
        return_source_documents=True # Important to return source documents so that the assistant can verify its answers against the retrieved information
    )
    
    print(" AI assistant successfully initialized !") 
    return qa_chain