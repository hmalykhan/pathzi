from accounts.services.user_embeddings import generate_user_embedding
from careers.models import CareerEmbedding

# adjust this import to your installed pgvector Django API
from pgvector.django import CosineDistance


def retrieve_similar_careers(user_embedding, top_k=10):
    results = (
        CareerEmbedding.objects
        .select_related("career")
        .annotate(distance=CosineDistance("embedding", user_embedding))
        .order_by("distance")[:top_k]
    )
    return results


def recommend_careers_for_user(user, saved_careers=None, explored_careers=None, top_k=10):
    user_result = generate_user_embedding(
        user=user,
        saved_careers=saved_careers,
        explored_careers=explored_careers,
    )

    results = retrieve_similar_careers(
        user_embedding=user_result["embedding"],
        top_k=top_k,
    )

    recommendations = []
    for row in results:
        recommendations.append({
            "career_id": row.career.id,
            "jobname": row.career.jobname,
            "career_type": row.career.career_type,
            "sub_type": row.career.sub_type,
            "distance": float(row.distance),
            "source_text": row.source_text,
        })

    return {
        "user_text": user_result["source_text"],
        "model_name": user_result["model_name"],
        "dimension": user_result["dimension"],
        "recommendations": recommendations,
    }