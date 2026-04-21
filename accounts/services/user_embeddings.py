# fetch/services/user_embeddings.py

from __future__ import annotations

from typing import Iterable, Optional
import requests

from accounts.services.user_text_builder import build_user_career_text

# from sentence_transformers import SentenceTransformer
# from typing import List
from accounts.models import UserEmbedding
import threading


# 🔹 Load model ONCE (global singleton)
# _model = None

# def get_model() -> SentenceTransformer:
#     global _model

#     if _model is None:
#         _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

#     return _model

# def embed_text(text: str) -> List[float]:
#     """
#     Convert a single text string into a 384-dim embedding vector.
#     """

#     if not text or not text.strip():
#         raise ValueError("Input text is empty")

#     model = get_model()

#     embedding = model.encode(text)

#     # Convert numpy → python list (important for pgvector)
#     return embedding.tolist()

import requests

def call_ml_api(text: str):
    res = requests.post(
        "http://206.189.18.64:8000/ml/embed/",
        json={"text": text},
        timeout=5
    )

    if res.status_code != 200:
        raise Exception(f"ML API failed: {res.text}")

    return res.json()["embedding"]

def generate_user_embedding(
    user,
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
        saved_careers=saved_careers,
        explored_careers=explored_careers,
    )

    if not source_text.strip():
        raise ValueError("Cannot generate user embedding: built user text is empty.")

    # embedding = embed_text(source_text)
    embedding = call_ml_api(source_text)

    return {
        "source_text": source_text,
        "embedding": embedding,
        "model_name": "sentence-transformers/all-MiniLM-L6-v2",
        "dimension": len(embedding),
    }

def generate_and_store_user_embedding(
    user,
    saved_careers: Optional[Iterable] = None,
    explored_careers: Optional[Iterable] = None,
):
    """
    Generate embedding and persist it to DB.
    """

    result = generate_user_embedding(
        user=user,
        saved_careers=saved_careers,
        explored_careers=explored_careers,
    )

    obj, created = UserEmbedding.objects.update_or_create(
        user=user,
        defaults={
            "embedding": result["embedding"],
            "source_text": result["source_text"],
            "model_name": result["model_name"],
        },
    )
    if obj:
        print("the embedding has been updated alhamdulillah.")

    return obj

def update_embedding_async(user):
    def task():
        try:
            generate_and_store_user_embedding(user)
        except Exception as e:
            print(f"Embedding failed: {e}")

    threading.Thread(target=task).start()