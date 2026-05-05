from django.contrib.auth import get_user_model
from django.core.cache import cache

from accounts.models import UserProfile
from accounts.services.recommendation_cache import get_list_cache_key
from accounts.services.career_recommender import recommend_careers_for_user
from accounts.services.user_embeddings import generate_and_store_user_embedding
from accounts.services.user_service import (
    get_career_queryset,
    get_explored_careers,
    get_saved_careers,
)

User = get_user_model()


def update_embedding_and_recs_for_user(user_id):
    print(f"[PIPELINE] start user_id={user_id}")

    user = User.objects.get(id=user_id)
    print("[PIPELINE] user loaded")

    profile, _ = UserProfile.objects.get_or_create(appuser=user)
    print("[PIPELINE] profile loaded")

    explored_careers = get_explored_careers(profile)
    saved_careers = get_saved_careers(profile)
    print("[PIPELINE] saved/explored loaded")

    generate_and_store_user_embedding(
        user,
        explored_careers=explored_careers,
        saved_careers=saved_careers,
    )
    print("[PIPELINE] embedding stored")

    queryset = get_career_queryset(user, profile)
    print("[PIPELINE] career queryset prepared")

    recs = recommend_careers_for_user(
        user=user,
        queryset=queryset,
        top_k=50,
    )
    print("[PIPELINE] recommendations generated")

    if recs and recs.get("recommendations"):
        ids = [r["career_id"] for r in recs["recommendations"]]
        print(f"[PIPELINE] caching {len(ids)} recommendation ids")

        cache.set(
            get_list_cache_key(user_id),
            ids,
            timeout=60 * 60 * 6,
        )

        print("[PIPELINE] cache set complete")

    else:
        print("[PIPELINE] no recommendations found")

    print("[PIPELINE] done")
    return True