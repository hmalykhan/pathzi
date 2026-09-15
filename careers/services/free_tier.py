"""
What a user still sees once the trial is over and nothing is paid for.

Decided with the user (2026-09-15): not a locked door. The home screen
keeps showing the careers they already explored or saved; what stops is
new recommendations. Saved careers, saved pathways and progress all stay
open and are handled by their own endpoints.

Controlled by settings.PAYWALL_ENFORCED, which is OFF by default. The
backend can therefore be deployed before the app has a paywall screen:
nothing changes for anyone until the flag is turned on, on the day the
new app ships. Turning it on early would strand users on the current app
with no way to subscribe.
"""
from django.conf import settings

from careers.models import Career, UserExploredCareer, UserSavedCareer


def paywall_enforced():
    return bool(getattr(settings, "PAYWALL_ENFORCED", False))


def free_tier_careers(profile):
    """
    The careers a free user keeps: everything they explored or saved.

    One row per career, newest interaction first, so the screen leads with
    what they looked at most recently.
    """
    if profile is None:
        return []

    explored = list(
        UserExploredCareer.objects
        .filter(user_profile=profile)
        .order_by("-created_at")
        .values_list("career_id", flat=True)
    )
    saved = list(
        UserSavedCareer.objects
        .filter(user_profile=profile)
        .order_by("-id")
        .values_list("career_id", flat=True)
    )

    ordered_ids, seen = [], set()
    for career_id in explored + saved:
        if career_id not in seen:
            seen.add(career_id)
            ordered_ids.append(career_id)

    if not ordered_ids:
        return []

    by_id = {c.id: c for c in Career.objects.filter(id__in=ordered_ids)}
    return [by_id[i] for i in ordered_ids if i in by_id]
