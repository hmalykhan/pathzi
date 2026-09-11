"""
match_score: how well a career fits the user, from 0 to 100.

It is the cosine similarity between the user's embedding and the career's
embedding - the measure the recommendation pipeline ranks careers by - read
from the embeddings already stored, so it needs no call to the ML service.

Raw similarities sit in a narrow band. Measured on the backup (2026-09-11,
80 users): a user's best match is 0.46-0.59 for 80% of users and their median
career about 0.35, so a plain similarity * 100 would show every career as a
middling match. The band is mapped linearly instead, clamped:
0.15 -> 0 and 0.60 -> 100. A typical user's best match then reads about 80,
their 10th best about 64 and their median career about 45.

Users without an embedding, and guests, get None: no score is made up.
"""
from pgvector.django import CosineDistance

from accounts.models import UserEmbedding
from careers.models import CareerEmbedding

SIMILARITY_FLOOR = 0.15    # -> 0   (about the 5th percentile of all user-career pairs)
SIMILARITY_CEILING = 0.60  # -> 100 (about the 90th percentile of users' best match)


def similarity_to_score(similarity: float) -> int:
    fraction = (similarity - SIMILARITY_FLOOR) / (SIMILARITY_CEILING - SIMILARITY_FLOOR)
    return round(min(max(fraction, 0.0), 1.0) * 100)


def match_scores(user, career_ids) -> dict:
    """{career_id: 0-100} for these careers; {} when the user has no embedding."""
    if not career_ids or not getattr(user, "is_authenticated", False):
        return {}
    vector = UserEmbedding.objects.filter(user_id=user.pk).values_list("embedding", flat=True).first()
    if vector is None:
        return {}
    rows = (
        CareerEmbedding.objects
        .filter(career_id__in=set(career_ids))
        .annotate(distance=CosineDistance("embedding", vector))
        .values_list("career_id", "distance")
    )
    return {career_id: similarity_to_score(1 - distance) for career_id, distance in rows}


def with_match_scores(rows, scores):
    """
    Copies of the serialized career rows with match_score added last (None when
    there is no score). Copies, so a cached response is never modified.
    """
    return [{**row, "match_score": scores.get(row["id"])} for row in rows]
