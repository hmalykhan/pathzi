# fetch/services/user_embeddings.py

from __future__ import annotations

from typing import Iterable, Optional

from accounts.services.user_text_builder import build_user_career_text

from sentence_transformers import SentenceTransformer
from typing import List

# 🔹 Load model ONCE (global singleton)
_model = None

def get_model() -> SentenceTransformer:
    global _model

    if _model is None:
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    return _model

def embed_text(text: str) -> List[float]:
    """
    Convert a single text string into a 384-dim embedding vector.
    """

    if not text or not text.strip():
        raise ValueError("Input text is empty")

    model = get_model()

    embedding = model.encode(text)

    # Convert numpy → python list (important for pgvector)
    return embedding.tolist()

def generate_user_embedding(
    user,
    category:str,
    saved_careers: Optional[Iterable] = None,
    explored_careers: Optional[Iterable] = None,
) -> dict:
    """
    Build user semantic text and embed it.

    Returns a structured payload instead of just the vector so this is
    easier to debug and use in retrieval services.
    """
    source_text = build_user_career_text(
        user=user,
        category=category,
        saved_careers=saved_careers,
        explored_careers=explored_careers,
    )

    if not source_text.strip():
        raise ValueError("Cannot generate user embedding: built user text is empty.")

    embedding = embed_text(source_text)

    return {
        "source_text": source_text,
        "embedding": embedding,
        "model_name": "sentence-transformers/all-MiniLM-L6-v2",
        "dimension": len(embedding),
    }