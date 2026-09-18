# -*- coding: utf-8 -*-
"""Проверка RAG-поиска изнутри контейнера (docker cp в контейнер, затем exec)."""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.services.rag import TheoryRetriever  # noqa: E402
from app.config import get_settings  # noqa: E402

r = TheoryRetriever(get_settings())
chunks = r.search("history", "Отмена крепостного права 1861")
print("chunks found:", len(chunks))
print("first:", chunks[0].text[:150] if chunks else "-")

rec = r.recommend("history", "T1", "Отмена крепостного права 1861 реформы Александра II")
print("recommended_topics:")
print(rec.recommended_topics)
