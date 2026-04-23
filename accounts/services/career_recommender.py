# from accounts.services.user_embeddings import generate_user_embedding
from careers.models import CareerEmbedding
from sklearn.metrics.pairwise import cosine_similarity
from accounts.models import UserEmbedding
from accounts.services.user_embeddings import schedule_embedding_update
from django.core.cache import cache
# adjust this import to your installed pgvector Django API
from pgvector.django import CosineDistance
import threading

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

        # if len(selected) >= top_k:
            # break

    return selected


def retrieve_similar_careers(user_embedding, queryset, top_k=10):
    results = (
        CareerEmbedding.objects
        .filter(career__in=queryset)
        .select_related("career")
        .annotate(distance=CosineDistance("embedding", user_embedding))
        # .order_by("distance")[:top_k]
        .order_by("distance")[:]
    )
    return results


# def recommend_careers_for_user(user, queryset, saved_careers=None, explored_careers=None, top_k=10):
#     user_result = generate_user_embedding(
#         user=user,
#         saved_careers=saved_careers,
#         explored_careers=explored_careers,
#     )
#     print(f"this is user result : {user_result}")

#     results = retrieve_similar_careers(
#         user_embedding=user_result["embedding"],
#         queryset=queryset,
#         top_k=top_k*5,
#     )

#     recommendations = []
#     for row in results:
#         recommendations.append({
#             "career_id": row.career.id,
#             "jobname": row.career.jobname,
#             "career_type": row.career.career_type,
#             "sub_type": row.career.sub_type,
#             "distance": float(row.distance),
#             "source_text": row.source_text,
#             "embedding": row.embedding,
#         })

#     print("RAW:", len(recommendations))

#     diversified = diversify_recommendations(
#         recommendations,
#         top_k=top_k
#     )

#     for row in diversified:
#         print("this is the distance : ",row['distance'])

#     print("FINAL:", len(diversified))

#     for r in diversified:
#         r.pop("embedding", None)

#     return {
#         "user_text": user_result["source_text"],
#         "model_name": user_result["model_name"],
#         "dimension": user_result["dimension"],
#         "recommendations": diversified,
#     }



def recommend_careers_for_user(user, queryset, top_k=10):
    try:
        user_embedding = user.embedding_record.embedding
        user_text = user.embedding_record.source_text
        model_name = user.embedding_record.model_name
        dimension = len(user_embedding)

    except UserEmbedding.DoesNotExist:
        # schedule_embedding_update(user)
        return {
            "user_text": None,
            "model_name": None,
            "dimension": None,
            "recommendations": None,
        }

    results = retrieve_similar_careers(
        user_embedding=user_embedding,
        queryset=queryset,
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

    diversified = diversify_recommendations(
        recommendations,
        top_k=top_k
    )

    for r in diversified:
        r.pop("embedding", None)

    return {
        "user_text": user_text,
        "model_name": model_name,
        "dimension": dimension,
        "recommendations": diversified,
    }

def precompute_recommendations_async(user, queryset):
    lock_key = f"recs_lock:{user.id}"

    # 🔒 prevent multiple threads
    if not cache.add(lock_key, True, timeout=20):
        return

    def task():
        try:
            print("alhamdulillah we are in precomputation.")
            recs = recommend_careers_for_user(
                user=user,
                queryset=queryset,
                top_k=100,
            )

            ids = [r["career_id"] for r in recs["recommendations"]]

            cache.set(f"user_recs:{user.id}", ids, timeout=60 * 60)
            print("alhamdulillah we are in precomputation and .")

        finally:
            cache.delete(lock_key)

    threading.Thread(target=task, daemon=True).start()
