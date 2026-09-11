"""
Progress tracker (GET /me/progress/): what the user has actually done,
computed from their own records - nothing here is estimated or made up.
"""
from collections import Counter
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db.models.functions import TruncDate
from django.utils import timezone

from accounts.models import UserProfile
from analytics import constants as C
from analytics.models import UserActivity
from careers.models import Career, UserExploredCareer, UserSavedCareer

# Streak days follow UK dates (the app is UK-only); the server clock is UTC.
STREAK_TZ = ZoneInfo("Europe/London")
STREAK_LOOKBACK_DAYS = 400  # analytics events are kept for 365 days anyway

# Unlocked by careers_explored. Keys and thresholds from BACKEND.md section 3.8.
ACHIEVEMENTS = (("first_steps", 10), ("career_expert", 50))

# A career counts as explored once the user has viewed, swiped or explored it.
EXPLORE_EVENTS = (C.CAREER_VIEWED, C.CAREER_SWIPED_RIGHT, C.CAREER_SWIPED_LEFT, C.CAREER_EXPLORED)

# The insight needs a few positive signals (right swipes, saved careers);
# below that, "strong interest" would be claiming more than we know.
INSIGHT_MIN_SIGNALS = 3


def total_careers() -> int:
    """Distinct careers in the catalogue (each is stored once per label it has)."""
    return Career.objects.values("job_slug").distinct().count()


def careers_explored(user, profile) -> int:
    """Distinct careers the user viewed, swiped or explored, counted once each."""
    slugs = set(
        UserActivity.objects
        .filter(user=user, activity_type__in=EXPLORE_EVENTS, career__isnull=False)
        .values_list("career__job_slug", flat=True)
    )
    if profile is not None:
        slugs |= set(
            UserExploredCareer.objects.filter(user_profile=profile).values_list("career__job_slug", flat=True)
        )
    return len(slugs)


def streak_days(user, today=None) -> int:
    """
    Consecutive UK days with any recorded activity, ending today - or ending
    yesterday, so a streak isn't lost before the user has had their day.
    """
    since = timezone.now() - timedelta(days=STREAK_LOOKBACK_DAYS)
    days = set(
        UserActivity.objects
        .filter(user=user, created_at__gte=since)
        .annotate(day=TruncDate("created_at", tzinfo=STREAK_TZ))
        .values_list("day", flat=True)
        .distinct()
    )
    today = today or timezone.now().astimezone(STREAK_TZ).date()
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


def insight(user, profile):
    """
    The user's strongest interest, from careers they swiped right on or saved:
    their top category and top careers. None until there are enough signals.
    """
    ids = list(
        UserActivity.objects
        .filter(user=user, activity_type=C.CAREER_SWIPED_RIGHT, career__isnull=False)
        .values_list("career_id", flat=True)
    )
    if profile is not None:
        ids += list(UserSavedCareer.objects.filter(user_profile=profile).values_list("career_id", flat=True))
    if len(ids) < INSIGHT_MIN_SIGNALS:
        return None

    labels = {cid: (category, name) for cid, category, name in
              Career.objects.filter(id__in=set(ids)).values_list("id", "sub_type", "jobname")}
    signals = [labels[i] for i in ids if i in labels]
    if len(signals) < INSIGHT_MIN_SIGNALS:
        return None

    top_category = Counter(category for category, _ in signals).most_common(1)[0][0]
    # Careers from that category only, so "especially X and Y" is always true.
    top_careers = [name for name, _ in Counter(n for c, n in signals if c == top_category).most_common(2)]
    text = f"You've shown strong interest in {top_category} careers, especially {' and '.join(top_careers)}."
    return {"text": text, "highlights": [top_category] + top_careers}


def progress_for(user) -> dict:
    profile = UserProfile.objects.filter(appuser=user).first()
    explored = careers_explored(user, profile)
    return {
        "careers_explored": explored,
        "total_careers": total_careers(),
        "saved_count": UserSavedCareer.objects.filter(user_profile=profile).count() if profile else 0,
        "category_count": len(profile.category or []) if profile else 0,
        "streak_days": streak_days(user),
        "achievements": [
            {"key": key, "unlocked": explored >= threshold, "threshold": threshold}
            for key, threshold in ACHIEVEMENTS
        ],
        "insight": insight(user, profile),
    }
