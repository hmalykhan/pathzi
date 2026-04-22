import re
from careers.models import Career
from accounts.models import UserSavedCareer, UserExploredCareer


# ============================
# USER IDS (FAST FOR RECOMMENDER)
# ============================

def get_saved_ids(profile):
    if not profile:
        return []
    return list(
        UserSavedCareer.objects.filter(
            user_profile=profile
        ).values_list("career_id", flat=True)
    )


def get_explored_ids(profile):
    if not profile:
        return []
    return list(
        UserExploredCareer.objects.filter(
            user_profile=profile
        ).values_list("career_id", flat=True)
    )


# ============================
# QUERYSET (OPTIMIZED)
# ============================

def get_saved_careers(profile):
    if not profile:
        return Career.objects.none()
    return Career.objects.filter(
        usersavedcareer__user_profile=profile
    ).order_by("id")


def get_explored_careers(profile):
    if not profile:
        return Career.objects.none()
    return Career.objects.filter(
        userexploredcareer__user_profile=profile
    ).order_by("id")


# ============================
# NORMALIZATION
# ============================

def normalize_sub_type(value: str) -> str:
    value = value or ""
    value = value.strip().lower()
    return re.sub(r"[ _-]+", "", value)


def norm_key(s: str) -> str:
    s = (s or "").strip().lower()
    return re.sub(r"[ _-]+", "", s)


# ============================
# MAIN QUERYSET LOGIC
# ============================

def get_filtered_base_queryset(user, profile):

    if not user or not user.is_authenticated:
        return Career.objects.none()

    if not profile:
        return Career.objects.none()

    raw_categories = getattr(profile, "category", None) or []

    if isinstance(raw_categories, str):
        raw_categories = [raw_categories]

    categories = []
    seen = set()

    for c in raw_categories:
        k = norm_key(c)
        if not k or k in seen:
            continue
        seen.add(k)
        categories.append(k)

    if not categories:
        return Career.objects.all().order_by("id")

    return Career.objects.filter(
        normalized_sub_type__in=categories
    ).order_by("id")


def get_career_queryset(user, profile):
    return get_filtered_base_queryset(user, profile)