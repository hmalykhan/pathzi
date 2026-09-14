"""
Who has access to Pathzi, and why.

One answer for the whole app: a paid subscription, the 7-day trial, or
referral days. Apple and Google know nothing about trials or referral days,
so this is worked out here and the app always asks us - never the store.

See PART2_PAYMENTS.md section 5.1 for the shape the app expects.
"""
import math
import uuid as uuid_lib
from datetime import timedelta

from django.utils import timezone

from accounts.models import UserProfile

TRIAL_DAYS = 7

# What the app may use with access, and what is left when the trial runs out.
FULL_FEATURES = ["recommendations", "routes", "reports", "search"]
FREE_FEATURES = ["explored_careers", "saved", "pathways", "progress", "referrals"]


def ensure_account_identity(profile):
    """
    Give a profile its purchase id and start its trial - once, and only if
    missing. This is what gives accounts created before launch a trial: it
    starts the first time they are looked at, not retroactively.
    """
    if profile is None:
        return None

    fields = []
    if profile.account_uuid is None:
        profile.account_uuid = uuid_lib.uuid4()
        fields.append("account_uuid")
    if profile.trial_started_at is None:
        now = timezone.now()
        profile.trial_started_at = now
        profile.trial_ends_at = now + timedelta(days=TRIAL_DAYS)
        fields += ["trial_started_at", "trial_ends_at"]

    if fields:
        profile.save(update_fields=fields)
    return profile


def _days_left(until, now):
    """Whole days remaining, rounded up, never negative."""
    if not until or until <= now:
        return 0
    return max(0, math.ceil((until - now).total_seconds() / 86400))


def access_for(user):
    """The access object the app reads. Never raises; unknown users get no access."""
    if not user or not getattr(user, "is_authenticated", False):
        return _no_access()

    profile = ensure_account_identity(UserProfile.objects.filter(appuser=user).first())
    if profile is None:
        return _no_access()

    now = timezone.now()
    billing = getattr(user, "billing", None)
    subscribed = bool(billing and billing.is_active)

    # Days earned while subscribed were parked so they would not be wasted.
    # The subscription has now lapsed, so they become free access. Done here
    # rather than on a webhook so it cannot be missed.
    if not subscribed and (profile.referral_days_banked or 0) > 0:
        _apply_banked_days(profile, now)

    trial_active = bool(profile.trial_ends_at and profile.trial_ends_at > now)
    referral_active = bool(profile.referral_access_until and profile.referral_access_until > now)

    # Access runs to the latest of the three, so buying during the trial - or
    # earning referral days while on it - never loses anything.
    ends = [d for d in (profile.trial_ends_at if trial_active else None,
                        profile.referral_access_until if referral_active else None,
                        billing.current_period_end if subscribed else None) if d]
    access_until = max(ends) if ends else None
    has_access = subscribed or trial_active or referral_active

    if subscribed:
        source = "subscription"
    elif trial_active:
        source = "trial"
    elif referral_active:
        source = "referral"
    else:
        source = "none"

    return {
        "has_access": has_access,
        "source": source,
        "access_until": access_until,
        "days_remaining": _days_left(access_until, now),
        "trial_active": trial_active,
        "trial_days": TRIAL_DAYS,
        "plan": billing.plan_id if subscribed else None,
        "store": None,          # filled in with RevenueCat (Phase 2)
        "auto_renewing": subscribed,
        "banked_referral_days": profile.referral_days_banked or 0,
        "features": FULL_FEATURES if has_access else FREE_FEATURES,
        "account_uuid": str(profile.account_uuid) if profile.account_uuid else None,
        "manage_url": None,     # filled in with RevenueCat (Phase 2)
    }


def _apply_banked_days(profile, now):
    """Turn banked referral days into free access, starting from whatever is left."""
    starts = [d for d in (profile.trial_ends_at, profile.referral_access_until) if d and d > now]
    base = max(starts) if starts else now

    profile.referral_access_until = base + timedelta(days=profile.referral_days_banked)
    profile.referral_days_banked = 0
    profile.save(update_fields=["referral_access_until", "referral_days_banked"])


def _no_access():
    return {
        "has_access": False,
        "source": "none",
        "access_until": None,
        "days_remaining": 0,
        "trial_active": False,
        "trial_days": TRIAL_DAYS,
        "plan": None,
        "store": None,
        "auto_renewing": False,
        "banked_referral_days": 0,
        "features": FREE_FEATURES,
        "account_uuid": None,
        "manage_url": None,
    }
