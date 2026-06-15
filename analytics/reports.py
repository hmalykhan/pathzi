"""
Read-side query helpers for the admin analytics dashboard.

Every function is a plain GROUP BY / COUNT over UserActivity (+ ProviderLead),
returning JSON-ready dicts/lists. No new tables. The matching `UserActivity`
indexes (activity_type+created_at, career+activity_type, user+activity_type)
keep these fast.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from . import constants as C
from .models import ProviderLead, UserActivity

User = get_user_model()


def _since(days):
    return timezone.now() - timedelta(days=days)


def overview(days=30):
    """Top-line totals for the dashboard header (last `days`, users all-time)."""
    qs = UserActivity.objects.filter(created_at__gte=_since(days))

    def n(activity_type):
        return qs.filter(activity_type=activity_type).count()

    right = n(C.CAREER_SWIPED_RIGHT)
    left = n(C.CAREER_SWIPED_LEFT)
    return {
        "days": days,
        "total_users": User.objects.count(),
        "total_career_views": n(C.CAREER_VIEWED),
        "total_swipes": right + left,
        "total_right_swipes": right,
        "total_left_swipes": left,
        "total_saves": n(C.CAREER_SAVED),
    }


def top_careers(activity_type, limit=20, days=None):
    """Top-N careers for a single activity type (e.g. most viewed / saved)."""
    qs = UserActivity.objects.filter(activity_type=activity_type, career__isnull=False)
    if days:
        qs = qs.filter(created_at__gte=_since(days))
    rows = (
        qs.values("career_id", "career__jobname")
        .annotate(count=Count("id"))
        .order_by("-count")[:limit]
    )
    return [
        {"career_id": r["career_id"], "jobname": r["career__jobname"], "count": r["count"]}
        for r in rows
    ]


def like_vs_skip_ratio(limit=20, days=None):
    """Per-career right vs left swipes + like ratio."""
    qs = UserActivity.objects.filter(
        activity_type__in=[C.CAREER_SWIPED_RIGHT, C.CAREER_SWIPED_LEFT],
        career__isnull=False,
    )
    if days:
        qs = qs.filter(created_at__gte=_since(days))
    rows = (
        qs.values("career_id", "career__jobname")
        .annotate(
            right=Count("id", filter=Q(activity_type=C.CAREER_SWIPED_RIGHT)),
            left=Count("id", filter=Q(activity_type=C.CAREER_SWIPED_LEFT)),
        )
        .order_by("-right")[:limit]
    )
    out = []
    for r in rows:
        total = r["right"] + r["left"]
        out.append(
            {
                "career_id": r["career_id"],
                "jobname": r["career__jobname"],
                "right": r["right"],
                "left": r["left"],
                "like_ratio": round(r["right"] / total, 3) if total else None,
            }
        )
    return out


def route_clicks(limit=20, days=None):
    """Most-clicked education routes (by route_id)."""
    qs = UserActivity.objects.filter(
        activity_type=C.ROUTE_CLICKED, route_id__isnull=False
    )
    if days:
        qs = qs.filter(created_at__gte=_since(days))
    rows = qs.values("route_id").annotate(count=Count("id")).order_by("-count")[:limit]
    return [{"route_id": r["route_id"], "count": r["count"]} for r in rows]


def provider_clicks(limit=20, days=None):
    """Most-clicked provider links (provider name carried in activity_value)."""
    qs = UserActivity.objects.filter(
        activity_type__in=[C.PROVIDER_LINK_CLICKED, C.CONNECT_BUTTON_CLICKED]
    ).exclude(activity_value__isnull=True).exclude(activity_value="")
    if days:
        qs = qs.filter(created_at__gte=_since(days))
    rows = (
        qs.values("activity_value")
        .annotate(count=Count("id"))
        .order_by("-count")[:limit]
    )
    return [{"provider": r["activity_value"], "count": r["count"]} for r in rows]


def consent_leads(limit=20):
    """Careers generating consent leads (from the ProviderLead table)."""
    rows = (
        ProviderLead.objects.filter(career__isnull=False)
        .values("career_id", "career__jobname")
        .annotate(count=Count("id"))
        .order_by("-count")[:limit]
    )
    return [
        {"career_id": r["career_id"], "jobname": r["career__jobname"], "leads": r["count"]}
        for r in rows
    ]


def timeseries(activity_type=None, days=30):
    """User activity by date (for trend charts)."""
    qs = UserActivity.objects.filter(created_at__gte=_since(days))
    if activity_type:
        qs = qs.filter(activity_type=activity_type)
    rows = (
        qs.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    return [{"date": r["day"].isoformat() if r["day"] else None, "count": r["count"]} for r in rows]


def career_summary(career_id):
    """Everything about one career: counts by type, routes, consent leads."""
    qs = UserActivity.objects.filter(career_id=career_id)
    by_type = {
        r["activity_type"]: r["count"]
        for r in qs.values("activity_type").annotate(count=Count("id"))
    }
    name = (
        qs.values_list("career__jobname", flat=True).first()
        or ProviderLead.objects.filter(career_id=career_id)
        .values_list("career__jobname", flat=True)
        .first()
    )
    routes = list(
        qs.filter(activity_type__in=[C.ROUTE_VIEWED, C.ROUTE_CLICKED], route_id__isnull=False)
        .values("route_id")
        .annotate(count=Count("id"))
        .order_by("-count")[:20]
    )
    return {
        "career_id": career_id,
        "jobname": name,
        "counts": by_type,
        "routes": routes,
        "consent_leads": ProviderLead.objects.filter(career_id=career_id).count(),
    }


def user_summary(user_id, timeline_limit=50):
    """One user's activity: counts by type + recent timeline."""
    qs = UserActivity.objects.filter(user_id=user_id)
    by_type = {
        r["activity_type"]: r["count"]
        for r in qs.values("activity_type").annotate(count=Count("id"))
    }
    timeline = [
        {
            "activity_type": a.activity_type,
            "career_id": a.career_id,
            "route_id": a.route_id,
            "activity_value": a.activity_value,
            "created_at": a.created_at.isoformat(),
        }
        for a in qs.order_by("-created_at")[:timeline_limit]
    ]
    return {"user_id": user_id, "counts": by_type, "timeline": timeline}


def popular_careers_by_location(limit_per_city=10, days=None, city=None):
    """
    Popular careers grouped by the user's profile city.

    Location is read at query time from UserProfile.city (joined via the
    event's user). Rows from anonymised/deleted users have no user and are
    therefore excluded — documented limitation of this report.
    """
    qs = (
        UserActivity.objects.filter(activity_type=C.CAREER_VIEWED, career__isnull=False)
        .exclude(user__isnull=True)
        .exclude(user__userprofile__city__isnull=True)
        .exclude(user__userprofile__city="")
    )
    if days:
        qs = qs.filter(created_at__gte=_since(days))
    if city:
        qs = qs.filter(user__userprofile__city__iexact=city)

    rows = (
        qs.values("user__userprofile__city", "career_id", "career__jobname")
        .annotate(count=Count("id"))
        .order_by("user__userprofile__city", "-count")
    )

    grouped = {}
    for r in rows:
        c = r["user__userprofile__city"]
        bucket = grouped.setdefault(c, [])
        if len(bucket) < limit_per_city:
            bucket.append(
                {
                    "career_id": r["career_id"],
                    "jobname": r["career__jobname"],
                    "count": r["count"],
                }
            )
    return grouped
