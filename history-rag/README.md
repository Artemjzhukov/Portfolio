# Local Knowledge Assistant (RAG) — Design Notes

## Status
In progress. Current corpus: 5000 documents, 15000 pages, Russian.

## Architecture Decisions
- **Chunking**: structure-aware split (by document section) + token-based 
  sub-chunking (~500 tokens, 15% overlap). Rationale: preserves semantic 
  units in historical narratives, avoids splitting events mid-chunk.
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
