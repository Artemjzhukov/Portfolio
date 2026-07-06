# Local Knowledge Assistant (RAG) — Design Notes

## Status
In progress. Current corpus: 5000 documents, 15000 pages, Russian.

## Architecture Decisions
- **Chunking**:D ocuments are currently added to the vector store without splitting. Planned: RecursiveCharacterTextSplitter  
  (~500 tokens, 15% overlap), structure-aware where possible. Rationale: preserves semantic units in historical narratives, avoids splitting events mid-chunk.  
- **Embeddings**: HuggingFace — chosen for Russian/English.
- **Vector Store**: Qdrant (Docker) — cosine similarity, top-k=5.
- **Generation**: Llama 3 8B via Ollama, quantized Q4/Q5 for local 
  inference speed.
- **Hallucination mitigation**: strict context-grounded system prompt + 
  source citation return.

## Known Limitations / Next Steps
- BM25 + dense retrieval — planned to improve exact-match recall for names/dates.
- planned: RAGAS
- Reindexing currently full-batch; incremental upsert planned as corpus grows.

## Why fully local
Source materials are privacy-sensitive (tutor-owned historical archives); 
zero external API calls is a hard requirement, not a default preference.

## Known Gaps (in progress)  
- **Vector dimension conflict handling**: not yet automated. Collection is created only if absent; changing the embedding model requires manual  
  collection recreation. Planned: compare existing collection's vector size against the active embedding model at startup, and either version   
  the collection name or raise an explicit, actionable error.  
- **Pydantic validation**: not yet implemented. Planned: a document schema (content, source, date, topic) validated before ingestion.  
- **Source citations**: format_docs currently concatenates raw page_content with no metadata; answers can't currently cite which document/chunk was used.  
- **Cross-machine portability**: currently relies on localhost defaults for Qdrant/Ollama; environment-variable config exists (QDRANT_HOST, OLLAMA_URL)  
  but hasn't been tested end-to-end on a genuinely separate client/server setup.  
- **Retrieval**: dense-only (top-k=3), no hybrid/BM25, no reranking, no similarity-score threshold — low-relevance results are currently filtered  
  only via the system prompt, not programmatically.  
- **No conversation memory** — each query is stateless.  
