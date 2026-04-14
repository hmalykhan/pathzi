from accounts.services.user_embeddings import generate_user_embedding
from careers.models import CareerEmbedding
from sklearn.metrics.pairwise import cosine_similarity

# adjust this import to your installed pgvector Django API
from pgvector.django import CosineDistance

def is_too_similar(vec1, vec2, threshold=0.88):
    sim = cosine_similarity([vec1], [vec2])[0][0]
    return sim > threshold

def diversify_recommendations(recommendations, top_k=10):
    selected = []

    for candidate in recommendations:
        is_duplicate = False

        for s in selected:
            if is_too_similar(candidate["embedding"], s["embedding"]):
                is_duplicate = True
                break

        if not is_duplicate:
            selected.append(candidate)

        if len(selected) >= top_k:
            break

    return selected


def retrieve_similar_careers(user_embedding, top_k=12):
    results = (
        CareerEmbedding.objects
        .select_related("career")
        .annotate(distance=CosineDistance("embedding", user_embedding))
        .order_by("distance")[:top_k]
    )
    return results


def recommend_careers_for_user(user, category:str, saved_careers=None, explored_careers=None, top_k=10):
    user_result = generate_user_embedding(
        user=user,
        category=category,
        saved_careers=saved_careers,
        explored_careers=explored_careers,
    )

    results = retrieve_similar_careers(
        user_embedding=user_result["embedding"],
        top_k=top_k * 5,
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
            "embedding": row.embedding,
        })

    print("RAW:", len(recommendations))

    diversified = diversify_recommendations(
        recommendations,
        top_k=top_k
    )

    print("FINAL:", len(diversified))

    for r in diversified:
        r.pop("embedding", None)

    return {
        "user_text": user_result["source_text"],
        "model_name": user_result["model_name"],
        "dimension": user_result["dimension"],
        "recommendations": diversified,
    }
