import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_qdrant import QdrantVectorStore
from core.database import get_vector_store   

load_dotenv()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

def format_docs(docs):
    """Joins documents into a single text for context."""
    return "\n\n".join(
        f"[{doc.metadata['source']}]\n{doc.page_content}"
        for doc in docs
    )

def create_history_assistant():
    print("Initializing the AI assistant model...")
    
    # 1. Инициализируем LLM (через Ollama)
    llm = ChatOllama(
        base_url=OLLAMA_URL,
        model="llama3:8b",
        temperature=0.3
    )
    
    # 2. retriever from Qdrant
    vector_store = get_vector_store()   
    retriever = vector_store.as_retriever(search_kwargs={"k": 3})
    
    # 3. Prompt (system + human)
    system_prompt = (
        "Вы являетесь профессиональным ассистентом по истории и обществознанию.\n"
        "Используйте предоставленный контекст, чтобы ответить на вопрос.\n"
        "Если вы не знаете ответа, честно скажите, что ответа нет в материалах.\n\n"
        "Контекст:\n{context}"
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}"),
    ])
    
    # 4. Build RAG-chain with LCEL
    print("Creating the LangChain retrieval chain (LCEL)...")
    
    rag_chain = (
        {
            "context": retriever | format_docs,   
            "input": RunnablePassthrough()        
        }
        | prompt                                  
        | llm                                     
        | StrOutputParser()                       
    )
    
    print("AI assistant successfully initialized!")
    return rag_chain