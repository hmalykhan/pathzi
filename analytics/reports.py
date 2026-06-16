"""
Read-side query helpers for the admin analytics dashboard.

Every function is a plain GROUP BY / COUNT over UserActivity (+ ProviderLead),
returning JSON-ready dicts/lists. No new tables. The matching `UserActivity`
indexes (activity_type+created_at, career+activity_type, user+activity_type)
keep these fast.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from careers.models import Career

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
        "total_careers": Career.objects.count(),
        "total_career_views": n(C.CAREER_VIEWED),
        "total_swipes": right + left,
        "total_right_swipes": right,
        "total_left_swipes": left,
        "total_saves": n(C.CAREER_SAVED),
    }


def top_careers(activity_type, offset=0, limit=10, days=None):
    """Careers ranked by a single activity type (e.g. most viewed / saved)."""
    qs = UserActivity.objects.filter(activity_type=activity_type, career__isnull=False)
    if days:
        qs = qs.filter(created_at__gte=_since(days))
    total = qs.values("career_id").distinct().count()
    rows = (
        qs.values("career_id", "career__jobname")
        .annotate(count=Count("id"))
        .order_by("-count")[offset:offset + limit]
    )
    return {
        "total": total,
        "results": [
            {"career_id": r["career_id"], "jobname": r["career__jobname"], "count": r["count"]}
            for r in rows
        ],
    }


def like_vs_skip_ratio(offset=0, limit=10, days=None):
    """Per-career right vs left swipes + like ratio (ranked)."""
    qs = UserActivity.objects.filter(
        activity_type__in=[C.CAREER_SWIPED_RIGHT, C.CAREER_SWIPED_LEFT],
        career__isnull=False,
    )
    if days:
        qs = qs.filter(created_at__gte=_since(days))
    total = qs.values("career_id").distinct().count()
    rows = (
        qs.values("career_id", "career__jobname")
        .annotate(
            right=Count("id", filter=Q(activity_type=C.CAREER_SWIPED_RIGHT)),
            left=Count("id", filter=Q(activity_type=C.CAREER_SWIPED_LEFT)),
        )
        .order_by("-right")[offset:offset + limit]
    )
    out = []
    for r in rows:
        tot = r["right"] + r["left"]
        out.append(
            {
                "career_id": r["career_id"],
                "jobname": r["career__jobname"],
                "right": r["right"],
                "left": r["left"],
                "like_ratio": round(r["right"] / tot, 3) if tot else None,
            }
        )
    return {"total": total, "results": out}


def route_clicks(offset=0, limit=10, days=None):
    """Most-clicked education routes (by route_id), ranked."""
    qs = UserActivity.objects.filter(
        activity_type=C.ROUTE_CLICKED, route_id__isnull=False
    )
    if days:
        qs = qs.filter(created_at__gte=_since(days))
    total = qs.values("route_id").distinct().count()
    rows = qs.values("route_id").annotate(count=Count("id")).order_by("-count")[offset:offset + limit]
    return {"total": total, "results": [{"route_id": r["route_id"], "count": r["count"]} for r in rows]}


def provider_clicks(offset=0, limit=10, days=None):
    """Most-clicked provider links (provider name in activity_value), ranked."""
    qs = UserActivity.objects.filter(
        activity_type__in=[C.PROVIDER_LINK_CLICKED, C.CONNECT_BUTTON_CLICKED]
    ).exclude(activity_value__isnull=True).exclude(activity_value="")
    if days:
        qs = qs.filter(created_at__gte=_since(days))
    total = qs.values("activity_value").distinct().count()
    rows = (
        qs.values("activity_value")
        .annotate(count=Count("id"))
        .order_by("-count")[offset:offset + limit]
    )
    return {"total": total, "results": [{"provider": r["activity_value"], "count": r["count"]} for r in rows]}


def consent_leads(offset=0, limit=10):
    """Careers generating consent leads (from the ProviderLead table), ranked."""
    base = ProviderLead.objects.filter(career__isnull=False)
    total = base.values("career_id").distinct().count()
    rows = (
        base.values("career_id", "career__jobname")
        .annotate(count=Count("id"))
        .order_by("-count")[offset:offset + limit]
    )
    return {
        "total": total,
        "results": [
            {"career_id": r["career_id"], "jobname": r["career__jobname"], "leads": r["count"]}
            for r in rows
        ],
    }


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


def careers_list(q=None, date_from=None, date_to=None, offset=0, limit=50):
    """
    Paginated list of careers with their analytics activity counts. Optional
    search (q over jobname/sub_type) and date range. Ordered by most active
    first; use search to find any specific career. Returns {total, results}.
    """
    act_q = Q()
    if date_from:
        act_q &= Q(activities__created_at__date__gte=date_from)
    if date_to:
        act_q &= Q(activities__created_at__date__lte=date_to)

    base = Career.objects.all()
    if q:
        base = base.filter(Q(jobname__icontains=q) | Q(sub_type__icontains=q))

    total = base.count()
    qs = base.annotate(event_count=Count("activities", filter=act_q)).order_by(
        "-event_count", "jobname"
    )[offset:offset + limit]

    results = [
        {
            "id": c.id,
            "jobname": c.jobname,
            "career_type": c.career_type,
            "sub_type": c.sub_type,
            "event_count": c.event_count,
        }
        for c in qs
    ]
    return {"total": total, "results": results}


def events_list(activity_types=None, q=None, date_from=None, date_to=None, offset=0, limit=50):
    """
    Paginated flat event feed for drill-downs from the KPI cards. Each row
    carries the career acted on plus the user (username/email) and event
    details. Optional filter by activity_types (list), search (q over
    user/career), and date range. Returns {total, results}.
    """
    qs = UserActivity.objects.select_related("user", "career")
    if activity_types:
        qs = qs.filter(activity_type__in=activity_types)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    if q:
        qs = qs.filter(
            Q(user__username__icontains=q)
            | Q(user__email__icontains=q)
            | Q(career__jobname__icontains=q)
        )

    total = qs.count()
    rows = []
    for a in qs.order_by("-created_at")[offset:offset + limit]:
        rows.append(
            {
                "created_at": a.created_at.isoformat(),
                "activity_type": a.activity_type,
                "career_id": a.career_id,
                "career": a.career.jobname if a.career_id and a.career else None,
                "user_id": a.user_id,
                "username": a.user.username if a.user_id and a.user else None,
                "email": a.user.email if a.user_id and a.user else None,
                "route_id": a.route_id,
                "activity_value": a.activity_value,
            }
        )
    return {"total": total, "results": rows}


def career_summary(career_id, date_from=None, date_to=None):
    """Everything about one career: headline stats, counts, routes, consent leads."""
    qs = UserActivity.objects.filter(career_id=career_id)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    by_type = {
        r["activity_type"]: r["count"]
        for r in qs.values("activity_type").annotate(count=Count("id"))
    }

    def g(t):
        return by_type.get(t, 0)

    stats = {
        "views": g(C.CAREER_VIEWED),
        "right_swipes": g(C.CAREER_SWIPED_RIGHT),
        "left_swipes": g(C.CAREER_SWIPED_LEFT),
        "total_swipes": g(C.CAREER_SWIPED_RIGHT) + g(C.CAREER_SWIPED_LEFT),
        "saves": g(C.CAREER_SAVED),
        "unsaves": g(C.CAREER_UNSAVED),
        "explores": g(C.CAREER_EXPLORED),
        "unexplores": g(C.CAREER_UNEXPLORED),
    }

    name = (
        Career.objects.filter(id=career_id).values_list("jobname", flat=True).first()
        or qs.values_list("career__jobname", flat=True).first()
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
        "total_events": qs.count(),
        "stats": stats,
        "counts": by_type,
        "routes": routes,
        "consent_leads": ProviderLead.objects.filter(career_id=career_id).count(),
    }


def users_list(q=None, date_from=None, date_to=None, offset=0, limit=50):
    """
    Paginated list of all users with their analytics activity counts. Optional
    search (q) and date range (counts events within [date_from, date_to]).
    Ordered by most active first. Returns {total, results}.
    """
    act_q = Q()
    if date_from:
        act_q &= Q(activities__created_at__date__gte=date_from)
    if date_to:
        act_q &= Q(activities__created_at__date__lte=date_to)

    base = User.objects.all()
    if q:
        base = base.filter(Q(username__icontains=q) | Q(email__icontains=q))

    total = base.count()
    qs = base.annotate(
        event_count=Count("activities", filter=act_q),
        last_active=Max("activities__created_at"),
    ).order_by("-event_count", "username")[offset:offset + limit]

    results = [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "event_count": u.event_count,
            "last_active": u.last_active.isoformat() if u.last_active else None,
        }
        for u in qs
    ]
    return {"total": total, "results": results}


def user_summary(user_id, date_from=None, date_to=None, timeline_limit=200):
    """One user's activity: counts by type + timeline, optionally date-filtered."""
    qs = UserActivity.objects.filter(user_id=user_id)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    by_type = {
        r["activity_type"]: r["count"]
        for r in qs.values("activity_type").annotate(count=Count("id"))
    }
    timeline = [
        {
            "activity_type": a.activity_type,
            "career_id": a.career_id,
            "career": a.career.jobname if a.career_id and a.career else None,
            "route_id": a.route_id,
            "activity_value": a.activity_value,
            "created_at": a.created_at.isoformat(),
        }
        for a in qs.select_related("career").order_by("-created_at")[:timeline_limit]
    ]
    info = User.objects.filter(id=user_id).values("username", "email").first() or {}
    return {
        "user_id": user_id,
        "username": info.get("username"),
        "email": info.get("email"),
        "total_events": qs.count(),
        "counts": by_type,
        "timeline": timeline,
    }


def popular_careers_by_location(offset=0, limit=10, days=None):
    """
    Cities ranked by career views, each with its single most-viewed career.
    Paginated by city. Location is read at query time from UserProfile.city
    (joined via the event's user); anonymised/deleted-user rows are excluded.
    Returns {total, results:[{city, jobname, count, city_views}]}.
    """
    base = (
        UserActivity.objects.filter(activity_type=C.CAREER_VIEWED, career__isnull=False)
        .exclude(user__isnull=True)
        .exclude(user__userprofile__city__isnull=True)
        .exclude(user__userprofile__city="")
    )
    if days:
        base = base.filter(created_at__gte=_since(days))

    city_field = "user__userprofile__city"
    city_totals = (
        base.values(city_field).annotate(city_views=Count("id")).order_by("-city_views")
    )
    total = city_totals.count()
    page = list(city_totals[offset:offset + limit])

    results = []
    for row in page:
        city = row[city_field]
        top = (
            base.filter(**{city_field: city})
            .values("career_id", "career__jobname")
            .annotate(count=Count("id"))
            .order_by("-count")
            .first()
        )
        results.append(
            {
                "city": city,
                "jobname": top["career__jobname"] if top else None,
                "count": top["count"] if top else 0,
                "city_views": row["city_views"],
            }
        )
    return {"total": total, "results": results}
