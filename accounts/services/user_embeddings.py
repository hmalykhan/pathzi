# fetch/services/user_embeddings.py

from __future__ import annotations

from typing import Iterable, Optional
import requests

from accounts.services.user_text_builder import build_user_career_text

# from sentence_transformers import SentenceTransformer
# from typing import List
from accounts.models import UserEmbedding
import threading
import logging
from django.core.cache import cache
import threading
import time

logger = logging.getLogger(__name__)
ML_API_URL = "http://206.189.18.64:8000/ml/embed/"


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
    for attempt in range(2):  # 1 retry
        try:
            response = requests.post(
                ML_API_URL,
                json={"text": text},
                timeout=(2, 5)
            )
            response.raise_for_status()
            return response.json().get("embedding")

        except requests.Timeout:
            logger.warning(f"Timeout attempt {attempt+1}")
        except requests.RequestException as e:
            logger.error(f"ML API error: {e}")
            break

    return None

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

def update_embedding_async(user, ex, sv):
    # 🔒 Prevent multiple threads for same user
    if getattr(user, "_embedding_running", False):
        return

    user._embedding_running = True

    def task():
        try:
            generate_and_store_user_embedding(user,explored_careers=ex, saved_careers=sv)
        except Exception as e:
            print(f"Embedding failed: {e}")
        finally:
            user._embedding_running = False

    thread = threading.Thread(target=task)
    thread.daemon = True   # 🔥 important (prevents hanging threads)
    thread.start()

def schedule_embedding_update(user,ex, sv, delay=5):
    key = f"embedding_schedule:{user.id}"

    # Each call updates timestamp
    now = time.time()
    cache.set(key, now, timeout=delay + 10)

    def task(start_time):
        time.sleep(delay)

        latest_time = cache.get(key)

        # Only run if this is the latest trigger
        if latest_time != start_time:
            return  # ❌ newer event happened → skip

        try:
            generate_and_store_user_embedding(user, explored_careers=ex, saved_careers=sv)
        finally:
            cache.delete(key)

    threading.Thread(
        target=task,
        args=(now,),
        daemon=True
    ).start()