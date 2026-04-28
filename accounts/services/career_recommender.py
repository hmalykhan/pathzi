# from accounts.services.user_embeddings import generate_user_embedding
from careers.models import CareerEmbedding
from sklearn.metrics.pairwise import cosine_similarity
from accounts.models import UserEmbedding, User
from accounts.services.user_embeddings import schedule_embedding_update
from django.core.cache import cache
# adjust this import to your installed pgvector Django API
from pgvector.django import CosineDistance
import threading
from accounts.services.user_service import get_career_queryset, get_explored_careers, get_saved_careers
from accounts.models import UserProfile
from accounts.services.recommendation_cache import get_list_cache_key, get_recs_lock_key
from accounts.services.user_embeddings import generate_and_store_user_embedding

def is_too_similar(vec1, vec2, threshold=0.95):
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


def retrieve_similar_careers(user_embedding, queryset, top_k=10):
    results = (
        CareerEmbedding.objects
        .filter(career__in=queryset)
        .select_related("career")
        .annotate(distance=CosineDistance("embedding", user_embedding))
        .order_by("distance")[:top_k]
        # .order_by("distance")[:]
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

def precompute_recommendations_async(user):
    

    # 🔒 prevent multiple threads
    if not cache.add(get_recs_lock_key(user.id), True, timeout=300):
        return

    def task():
        try:
            print("alhamdulillah we are in precomputation.")
            profile, _ = UserProfile.objects.get_or_create(appuser=user)
            recs = recommend_careers_for_user(
                user=user,
                queryset=get_career_queryset(user, profile),
                top_k=50,
            )

            if not recs or not recs.get("recommendations"):
                print("recomendations is empty in precompute_recommendatins_async.")
                return

            ids = [r["career_id"] for r in recs["recommendations"]]

            cache.set(get_list_cache_key(user.id), ids, timeout=60 * 60 * 6)
            print("alhamdulillah we are in precomputation and .")

        finally:
            cache.delete(get_recs_lock_key(user.id))

    threading.Thread(target=task, daemon=True).start()

def update_embedding_and_recs_async(user_id):

    lock_key = f"pipeline_lock:{user_id}"

    # 🔒 prevent multiple pipelines
    if not cache.add(lock_key, True, timeout=300):
        return

    def task():
        try:
            print("STEP 1: embedding")

            user = User.objects.get(id=user_id)
            profile, _ = UserProfile.objects.get_or_create(appuser=user)

            ex = get_explored_careers(profile)
            sv = get_saved_careers(profile)

            # STEP 1
            generate_and_store_user_embedding(
                user,
                explored_careers=ex,
                saved_careers=sv
            )

            print("STEP 2: recommendations")

            # STEP 2
            recs = recommend_careers_for_user(
                user=user,
                queryset=get_career_queryset(user, profile),
                top_k=50,
            )

            if recs and recs.get("recommendations"):
                ids = [r["career_id"] for r in recs["recommendations"]]
                cache.set(get_list_cache_key(user_id), ids, timeout=60 * 60 * 6)

        except Exception as e:
            print(f"Pipeline failed: {e}")

        finally:
            # 🔓 ALWAYS release lock
            cache.delete(lock_key)

    threading.Thread(target=task, daemon=True).start()
