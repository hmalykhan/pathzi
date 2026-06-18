# careers/services/embeddings.py

from typing import List
import logging

import requests

logger = logging.getLogger(__name__)

# Embeddings are produced by the dedicated embedding microservice (DO droplet),
# not in-process. This keeps torch/transformers out of the main backend and
# guarantees careers and users are embedded by the exact same model
# (essential for accurate cosine-distance matching).
ML_API_URL = "http://206.189.18.64:8000/ml/embed/"


def _call_ml_api(text: str) -> List[float]:
    """POST text to the embedding microservice and return its 384-dim vector."""
    for attempt in range(2):  # 1 retry
        try:
            response = requests.post(ML_API_URL, json={"text": text}, timeout=(2, 5))
            response.raise_for_status()
            embedding = response.json().get("embedding")
            if embedding is None:
                raise ValueError("ML API returned no embedding")
            return embedding
        except requests.Timeout:
            logger.warning(f"ML API timeout, attempt {attempt + 1}")
        except requests.RequestException as e:
            logger.error(f"ML API error: {e}")
            break

    raise RuntimeError("Failed to fetch embedding from ML microservice")


def embed_text(text: str) -> List[float]:
    """
    Convert a single text string into a 384-dim embedding vector.
    """
    if not text or not text.strip():
        raise ValueError("Input text is empty")

    return _call_ml_api(text)


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Batch embedding. The microservice embeds one text per request, so this
    loops; it is the single place to optimise if a batch endpoint is added.
    """
    if not texts:
        return []

    return [_call_ml_api(t) for t in texts]
