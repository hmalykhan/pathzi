from django.core.cache import cache
from django.db import transaction

from accounts.services.recommendation_cache import (
    get_explored_cache_key,
    get_list_cache_key,
    get_saved_cache_key,
)
from careers.models import Career, UserExploredCareer, UserSavedCareer
from careers.services.recommendation_triggers import trigger_recs_debounced

from analytics.services import log_activity
from analytics import constants as analytics_constants


def apply_bulk_career_interactions(user, profile, items):
    """
    Applies final saved/explored states for many careers.

    Expected items:
    [
        {"career_id": 1, "saved": True},
        {"career_id": 2, "saved": False},
        {"career_id": 3, "explored": True},
        {"career_id": 4, "saved": True, "explored": True},
    ]
    """

    career_ids = [item["career_id"] for item in items]

    existing_career_ids = set(
        Career.objects.filter(id__in=career_ids)
        .values_list("id", flat=True)
    )

    missing_ids = sorted(set(career_ids) - existing_career_ids)

    if missing_ids:
        return {
            "ok": False,
            "missing_ids": missing_ids,
        }

    save_true_ids = []
    save_false_ids = []
    explore_true_ids = []
    explore_false_ids = []

    for item in items:
        career_id = item["career_id"]

        if "saved" in item:
            if item["saved"]:
                save_true_ids.append(career_id)
            else:
                save_false_ids.append(career_id)

        if "explored" in item:
            if item["explored"]:
                explore_true_ids.append(career_id)
            else:
                explore_false_ids.append(career_id)

    saved_changed = False
    explored_changed = False

    with transaction.atomic():
        if save_true_ids:
            existing_saved_ids = set(
                UserSavedCareer.objects.filter(
                    user_profile=profile,
                    career_id__in=save_true_ids,
                ).values_list("career_id", flat=True)
            )

            to_create = [
                UserSavedCareer(
                    user_profile=profile,
                    career_id=career_id,
                )
                for career_id in save_true_ids
                if career_id not in existing_saved_ids
            ]

            if to_create:
                UserSavedCareer.objects.bulk_create(
                    to_create,
                    ignore_conflicts=True,
                )
                saved_changed = True

        if save_false_ids:
            deleted, _ = UserSavedCareer.objects.filter(
                user_profile=profile,
                career_id__in=save_false_ids,
            ).delete()

            if deleted:
                saved_changed = True

        if explore_true_ids:
            existing_explored_ids = set(
                UserExploredCareer.objects.filter(
                    user_profile=profile,
                    career_id__in=explore_true_ids,
                ).values_list("career_id", flat=True)
            )

            to_create = [
                UserExploredCareer(
                    user_profile=profile,
                    career_id=career_id,
                )
                for career_id in explore_true_ids
                if career_id not in existing_explored_ids
            ]

            if to_create:
                UserExploredCareer.objects.bulk_create(
                    to_create,
                    ignore_conflicts=True,
                )
                explored_changed = True

        if explore_false_ids:
            deleted, _ = UserExploredCareer.objects.filter(
                user_profile=profile,
                career_id__in=explore_false_ids,
            ).delete()

            if deleted:
                explored_changed = True

    if saved_changed:
        cache.delete(get_saved_cache_key(user.id))

    if explored_changed:
        cache.delete(get_explored_cache_key(user.id))

    if saved_changed or explored_changed:
        cache.delete(get_list_cache_key(user.id))
        trigger_recs_debounced(user.id)

    # Analytics: one event per requested interaction (Lane A). log_activity
    # never raises, so this can't affect the bulk result. We log the user's
    # intent across all four lists, matching the single-action endpoints.
    for activity_type, career_ids in (
        (analytics_constants.CAREER_SAVED, save_true_ids),
        (analytics_constants.CAREER_UNSAVED, save_false_ids),
        (analytics_constants.CAREER_EXPLORED, explore_true_ids),
        (analytics_constants.CAREER_UNEXPLORED, explore_false_ids),
    ):
        for career_id in career_ids:
            log_activity(
                user=user,
                activity_type=activity_type,
                career=career_id,
                metadata={"source": "bulk_interactions"},
            )

    return {
        "ok": True,
        "updated_count": len(items),
        "saved_changed": saved_changed,
        "explored_changed": explored_changed,
    }