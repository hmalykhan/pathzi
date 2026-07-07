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


def _range(qs, field, date_from, date_to):
    """Filter a queryset to [date_from, date_to] on `field` (either bound optional)."""
    if date_from:
        qs = qs.filter(**{f"{field}__date__gte": date_from})
    if date_to:
        qs = qs.filter(**{f"{field}__date__lte": date_to})
    return qs


def overview(date_from=None, date_to=None):
    """Top-line totals for the dashboard header (all-time when no range given)."""
    qs = UserActivity.objects.all()
    qs = _range(qs, "created_at", date_from, date_to)

    # All per-type counts in ONE grouped query instead of one round-trip each.
    by_type = dict(
        qs.filter(
            activity_type__in=[
                C.CAREER_VIEWED, C.CAREER_SWIPED_RIGHT,
                C.CAREER_SWIPED_LEFT, C.CAREER_SAVED,
            ]
        )
        .values_list("activity_type")
        .annotate(n=Count("id"))
    )
    right = by_type.get(C.CAREER_SWIPED_RIGHT, 0)
    left = by_type.get(C.CAREER_SWIPED_LEFT, 0)
    return {
        "total_users": User.objects.count(),
        "total_careers": Career.objects.count(),
        "total_career_views": by_type.get(C.CAREER_VIEWED, 0),
        "total_swipes": right + left,
        "total_right_swipes": right,
        "total_left_swipes": left,
        "total_saves": by_type.get(C.CAREER_SAVED, 0),
    }


def top_careers(activity_type, offset=0, limit=10, date_from=None, date_to=None):
    """Careers ranked by a single activity type (e.g. most viewed / saved)."""
    qs = UserActivity.objects.filter(activity_type=activity_type, career__isnull=False)
    qs = _range(qs, "created_at", date_from, date_to)
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


def career_engagement_users(activity_type, offset=0, limit=10, date_from=None, date_to=None, users_per_career=2000):
    """
    Top careers for an activity type (e.g. most viewed / saved), each with the
    list of users who performed that activity on the career. Powers the hover
    side-panel, the "View all" grouped sheet and the grouped PDF export.

    Two queries regardless of how many careers are returned: one to rank the
    careers, one to pull (career, user) counts for just those careers.
    Returns {total, activity_type, results:[{career_id, jobname, count, users:[...]}]}.
    """
    qs = UserActivity.objects.filter(activity_type=activity_type, career__isnull=False)
    qs = _range(qs, "created_at", date_from, date_to)

    # FAST PATH ("View all" / PDF want everything): a single group-by (career, user)
    # query, folded into careers + totals in Python. Avoids the separate COUNT and
    # career-ranking round-trips to the remote DB (3 queries -> 1).
    if offset == 0 and limit >= 1000:
        rows = qs.values(
            "career_id", "career__jobname", "user_id", "user__username", "user__email"
        ).annotate(count=Count("id"), last_at=Max("created_at"))
        careers = {}
        for r in rows:
            c = careers.get(r["career_id"])
            if c is None:
                c = careers[r["career_id"]] = {
                    "career_id": r["career_id"],
                    "jobname": r["career__jobname"],
                    "count": 0,
                    "users": [],
                }
            c["count"] += r["count"]  # includes anonymous events in the career total
            if r["user_id"] is not None:
                c["users"].append(
                    {
                        "user_id": r["user_id"],
                        "username": r["user__username"],
                        "email": r["user__email"],
                        "count": r["count"],
                        "last_at": r["last_at"].isoformat() if r["last_at"] else None,
                    }
                )
        out = sorted(careers.values(), key=lambda c: c["count"], reverse=True)
        for c in out:
            c["users"].sort(key=lambda u: u["count"], reverse=True)
            c["users"] = c["users"][:users_per_career]
        return {"total": len(out), "activity_type": activity_type, "results": out}

    total = qs.values("career_id").distinct().count()
    career_rows = list(
        qs.values("career_id", "career__jobname")
        .annotate(count=Count("id"))
        .order_by("-count")[offset:offset + limit]
    )
    career_ids = [r["career_id"] for r in career_rows]

    by_career = {}
    if career_ids:
        user_rows = (
            qs.filter(career_id__in=career_ids, user__isnull=False)
            .values("career_id", "user_id", "user__username", "user__email")
            .annotate(count=Count("id"), last_at=Max("created_at"))
            .order_by("career_id", "-count")
        )
        for u in user_rows:
            by_career.setdefault(u["career_id"], []).append(
                {
                    "user_id": u["user_id"],
                    "username": u["user__username"],
                    "email": u["user__email"],
                    "count": u["count"],
                    "last_at": u["last_at"].isoformat() if u["last_at"] else None,
                }
            )

    results = [
        {
            "career_id": r["career_id"],
            "jobname": r["career__jobname"],
            "count": r["count"],
            "users": by_career.get(r["career_id"], [])[:users_per_career],
        }
        for r in career_rows
    ]
    return {"total": total, "activity_type": activity_type, "results": results}


def career_activity_users(career_id, activity_type, date_from=None, date_to=None, users_limit=2000):
    """
    Users who did one activity (e.g. viewed / saved) on one career, with each
    user's count. Powers the lazy hover popup on the Most Viewed / Most Saved
    charts. Single query: group by user (anon folded into the total).
    Returns {career_id, jobname, count, users:[...]}.
    """
    qs = UserActivity.objects.filter(career_id=career_id, activity_type=activity_type)
    qs = _range(qs, "created_at", date_from, date_to)

    rows = qs.values(
        "user_id", "user__username", "user__email", "career__jobname"
    ).annotate(count=Count("id"), last_at=Max("created_at"))

    name, total, users = None, 0, []
    for r in rows:
        name = name or r["career__jobname"]
        total += r["count"]  # includes anonymous events in the career total
        if r["user_id"] is not None:
            users.append(
                {
                    "user_id": r["user_id"],
                    "username": r["user__username"],
                    "email": r["user__email"],
                    "count": r["count"],
                    "last_at": r["last_at"].isoformat() if r["last_at"] else None,
                }
            )
    users.sort(key=lambda u: u["count"], reverse=True)
    if name is None:
        name = Career.objects.filter(id=career_id).values_list("jobname", flat=True).first()
    return {"career_id": career_id, "jobname": name, "count": total, "users": users[:users_limit]}


def like_vs_skip_ratio(offset=0, limit=10, date_from=None, date_to=None):
    """Per-career right vs left swipes + like ratio (ranked)."""
    qs = UserActivity.objects.filter(
        activity_type__in=[C.CAREER_SWIPED_RIGHT, C.CAREER_SWIPED_LEFT],
        career__isnull=False,
    )
    qs = _range(qs, "created_at", date_from, date_to)
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


def career_swipe_users(career_id, date_from=None, date_to=None, users_limit=2000):
    """
    Users who swiped on one career, each with their right (like) and left (skip)
    counts. Powers the hover popup on the "Like vs Skip (per career)" table.
    Returns {career_id, jobname, right, left, users:[...]}.
    """
    qs = UserActivity.objects.filter(
        career_id=career_id,
        activity_type__in=[C.CAREER_SWIPED_RIGHT, C.CAREER_SWIPED_LEFT],
    )
    qs = _range(qs, "created_at", date_from, date_to)

    rows = (
        qs.filter(user__isnull=False)
        .values("user_id", "user__username", "user__email")
        .annotate(
            right=Count("id", filter=Q(activity_type=C.CAREER_SWIPED_RIGHT)),
            left=Count("id", filter=Q(activity_type=C.CAREER_SWIPED_LEFT)),
            last_at=Max("created_at"),
        )
        .order_by("-right", "-left")[:users_limit]
    )
    users = [
        {
            "user_id": r["user_id"],
            "username": r["user__username"],
            "email": r["user__email"],
            "right": r["right"],
            "left": r["left"],
            "last_at": r["last_at"].isoformat() if r["last_at"] else None,
        }
        for r in rows
    ]
    name = Career.objects.filter(id=career_id).values_list("jobname", flat=True).first()
    return {
        "career_id": career_id,
        "jobname": name,
        "right": sum(u["right"] for u in users),
        "left": sum(u["left"] for u in users),
        "users": users,
    }


def swipe_engagement_users(offset=0, limit=10, date_from=None, date_to=None, users_per_career=2000):
    """
    Careers ranked by right-swipes, each with the list of users who swiped on it
    (with per-user right/left counts). Powers the grouped "View all" sheet and
    grouped PDF for the Like vs Skip section. Two queries regardless of how many
    careers are returned.
    Returns {total, results:[{career_id, jobname, right, left, like_ratio, users:[...]}]}.
    """
    qs = UserActivity.objects.filter(
        activity_type__in=[C.CAREER_SWIPED_RIGHT, C.CAREER_SWIPED_LEFT],
        career__isnull=False,
    )
    qs = _range(qs, "created_at", date_from, date_to)

    # FAST PATH ("View all" / PDF want everything): one group-by (career, user)
    # query folded in Python — avoids the separate COUNT and ranking round-trips.
    if offset == 0 and limit >= 1000:
        rows = qs.values(
            "career_id", "career__jobname", "user_id", "user__username", "user__email"
        ).annotate(
            right=Count("id", filter=Q(activity_type=C.CAREER_SWIPED_RIGHT)),
            left=Count("id", filter=Q(activity_type=C.CAREER_SWIPED_LEFT)),
            last_at=Max("created_at"),
        )
        careers = {}
        for r in rows:
            c = careers.get(r["career_id"])
            if c is None:
                c = careers[r["career_id"]] = {
                    "career_id": r["career_id"],
                    "jobname": r["career__jobname"],
                    "right": 0,
                    "left": 0,
                    "users": [],
                }
            c["right"] += r["right"]
            c["left"] += r["left"]
            if r["user_id"] is not None:
                c["users"].append(
                    {
                        "user_id": r["user_id"],
                        "username": r["user__username"],
                        "email": r["user__email"],
                        "right": r["right"],
                        "left": r["left"],
                        "last_at": r["last_at"].isoformat() if r["last_at"] else None,
                    }
                )
        out = sorted(careers.values(), key=lambda c: c["right"], reverse=True)
        for c in out:
            tot = c["right"] + c["left"]
            c["like_ratio"] = round(c["right"] / tot, 3) if tot else None
            c["users"].sort(key=lambda u: (u["right"], u["left"]), reverse=True)
            c["users"] = c["users"][:users_per_career]
        return {"total": len(out), "results": out}

    total = qs.values("career_id").distinct().count()
    career_rows = list(
        qs.values("career_id", "career__jobname")
        .annotate(
            right=Count("id", filter=Q(activity_type=C.CAREER_SWIPED_RIGHT)),
            left=Count("id", filter=Q(activity_type=C.CAREER_SWIPED_LEFT)),
        )
        .order_by("-right")[offset:offset + limit]
    )
    career_ids = [r["career_id"] for r in career_rows]

    by_career = {}
    if career_ids:
        user_rows = (
            qs.filter(career_id__in=career_ids, user__isnull=False)
            .values("career_id", "user_id", "user__username", "user__email")
            .annotate(
                right=Count("id", filter=Q(activity_type=C.CAREER_SWIPED_RIGHT)),
                left=Count("id", filter=Q(activity_type=C.CAREER_SWIPED_LEFT)),
                last_at=Max("created_at"),
            )
            .order_by("career_id", "-right", "-left")
        )
        for u in user_rows:
            by_career.setdefault(u["career_id"], []).append(
                {
                    "user_id": u["user_id"],
                    "username": u["user__username"],
                    "email": u["user__email"],
                    "right": u["right"],
                    "left": u["left"],
                    "last_at": u["last_at"].isoformat() if u["last_at"] else None,
                }
            )

    results = []
    for r in career_rows:
        tot = r["right"] + r["left"]
        results.append(
            {
                "career_id": r["career_id"],
                "jobname": r["career__jobname"],
                "right": r["right"],
                "left": r["left"],
                "like_ratio": round(r["right"] / tot, 3) if tot else None,
                "users": by_career.get(r["career_id"], [])[:users_per_career],
            }
        )
    return {"total": total, "results": results}


def swipe_direction_users(direction, offset=0, limit=10, date_from=None, date_to=None, users_per_career=2000):
    """
    Careers that received one swipe direction ("right" = like / "left" = skip),
    each with the users who swiped that way and their counts. Powers the donut's
    hover popup (per segment) and its grouped "View all". Single group-by query.
    Returns {total, direction, results:[{career_id, jobname, count, users:[...]}]}.
    """
    activity = C.CAREER_SWIPED_RIGHT if direction == "right" else C.CAREER_SWIPED_LEFT
    qs = UserActivity.objects.filter(activity_type=activity, career__isnull=False)
    qs = _range(qs, "created_at", date_from, date_to)

    rows = qs.values(
        "career_id", "career__jobname", "user_id", "user__username", "user__email"
    ).annotate(count=Count("id"), last_at=Max("created_at"))

    careers = {}
    for r in rows:
        c = careers.get(r["career_id"])
        if c is None:
            c = careers[r["career_id"]] = {
                "career_id": r["career_id"],
                "jobname": r["career__jobname"],
                "count": 0,
                "users": [],
            }
        c["count"] += r["count"]
        if r["user_id"] is not None:
            c["users"].append(
                {
                    "user_id": r["user_id"],
                    "username": r["user__username"],
                    "email": r["user__email"],
                    "count": r["count"],
                    "last_at": r["last_at"].isoformat() if r["last_at"] else None,
                }
            )
    out = sorted(careers.values(), key=lambda c: c["count"], reverse=True)
    for c in out:
        c["users"].sort(key=lambda u: u["count"], reverse=True)
        c["users"] = c["users"][:users_per_career]
    total = len(out)
    if offset or limit < total:
        out = out[offset:offset + limit]
    return {"total": total, "direction": direction, "results": out}


def route_clicks(offset=0, limit=10, date_from=None, date_to=None):
    """Most-clicked education routes (by route_id), ranked."""
    qs = UserActivity.objects.filter(
        activity_type=C.ROUTE_CLICKED, route_id__isnull=False
    )
    qs = _range(qs, "created_at", date_from, date_to)
    total = qs.values("route_id").distinct().count()
    rows = qs.values("route_id").annotate(count=Count("id")).order_by("-count")[offset:offset + limit]
    return {"total": total, "results": [{"route_id": r["route_id"], "count": r["count"]} for r in rows]}


# Per-route-type Count() expressions reused by the three functions below.
def _route_annotations():
    return {
        "course": Count("id", filter=Q(route_id=C.ROUTE_COURSE)),
        "apprenticeship": Count("id", filter=Q(route_id=C.ROUTE_APPRENTICESHIP)),
        "job": Count("id", filter=Q(route_id=C.ROUTE_JOB)),
        "total": Count("id"),
    }


def route_clicks_by_career(offset=0, limit=10, date_from=None, date_to=None):
    """
    Careers ranked by total route clicks, split into course / apprenticeship /
    job columns. Powers the "Education Routes by Career" table. Two queries.
    Returns {total, results:[{career_id, jobname, course, apprenticeship, job, total}]}.
    """
    qs = UserActivity.objects.filter(
        activity_type=C.ROUTE_CLICKED, career__isnull=False, route_id__isnull=False
    )
    qs = _range(qs, "created_at", date_from, date_to)
    total = qs.values("career_id").distinct().count()
    rows = (
        qs.values("career_id", "career__jobname")
        .annotate(**_route_annotations())
        .order_by("-total")[offset:offset + limit]
    )
    return {
        "total": total,
        "results": [
            {
                "career_id": r["career_id"],
                "jobname": r["career__jobname"],
                "course": r["course"],
                "apprenticeship": r["apprenticeship"],
                "job": r["job"],
                "total": r["total"],
            }
            for r in rows
        ],
    }


def career_route_users(career_id, date_from=None, date_to=None, users_limit=2000):
    """
    Users who clicked routes on one career, each with their course / apprenticeship
    / job click counts. Powers the lazy hover popup on the routes table. One query.
    Returns {career_id, jobname, course, apprenticeship, job, total, users:[...]}.
    """
    qs = UserActivity.objects.filter(
        activity_type=C.ROUTE_CLICKED, career_id=career_id, route_id__isnull=False
    )
    qs = _range(qs, "created_at", date_from, date_to)

    rows = qs.values(
        "user_id", "user__username", "user__email", "career__jobname"
    ).annotate(last_at=Max("created_at"), **_route_annotations())

    name, agg, users = None, {"course": 0, "apprenticeship": 0, "job": 0, "total": 0}, []
    for r in rows:
        name = name or r["career__jobname"]
        for k in agg:
            agg[k] += r[k]
        if r["user_id"] is not None:
            users.append(
                {
                    "user_id": r["user_id"],
                    "username": r["user__username"],
                    "email": r["user__email"],
                    "course": r["course"],
                    "apprenticeship": r["apprenticeship"],
                    "job": r["job"],
                    "total": r["total"],
                    "last_at": r["last_at"].isoformat() if r["last_at"] else None,
                }
            )
    users.sort(key=lambda u: u["total"], reverse=True)
    if name is None:
        name = Career.objects.filter(id=career_id).values_list("jobname", flat=True).first()
    return {"career_id": career_id, "jobname": name, **agg, "users": users[:users_limit]}


def route_engagement_users(offset=0, limit=10, date_from=None, date_to=None, users_per_career=2000):
    """
    Careers ranked by total route clicks, each with the users who clicked (per-user
    course/apprenticeship/job counts). Powers the grouped "View all" sheet / PDF.
    Single group-by query in the fetch-all fast path.
    Returns {total, results:[{career_id, jobname, course, apprenticeship, job, total, users:[...]}]}.
    """
    qs = UserActivity.objects.filter(
        activity_type=C.ROUTE_CLICKED, career__isnull=False, route_id__isnull=False
    )
    qs = _range(qs, "created_at", date_from, date_to)

    # FAST PATH (View all / PDF want everything): one group-by (career, user) query.
    if offset == 0 and limit >= 1000:
        rows = qs.values(
            "career_id", "career__jobname", "user_id", "user__username", "user__email"
        ).annotate(last_at=Max("created_at"), **_route_annotations())
        careers = {}
        for r in rows:
            c = careers.get(r["career_id"])
            if c is None:
                c = careers[r["career_id"]] = {
                    "career_id": r["career_id"],
                    "jobname": r["career__jobname"],
                    "course": 0, "apprenticeship": 0, "job": 0, "total": 0,
                    "users": [],
                }
            for k in ("course", "apprenticeship", "job", "total"):
                c[k] += r[k]
            if r["user_id"] is not None:
                c["users"].append(
                    {
                        "user_id": r["user_id"],
                        "username": r["user__username"],
                        "email": r["user__email"],
                        "course": r["course"],
                        "apprenticeship": r["apprenticeship"],
                        "job": r["job"],
                        "total": r["total"],
                        "last_at": r["last_at"].isoformat() if r["last_at"] else None,
                    }
                )
        out = sorted(careers.values(), key=lambda c: c["total"], reverse=True)
        for c in out:
            c["users"].sort(key=lambda u: u["total"], reverse=True)
            c["users"] = c["users"][:users_per_career]
        return {"total": len(out), "results": out}

    total = qs.values("career_id").distinct().count()
    career_rows = list(
        qs.values("career_id", "career__jobname")
        .annotate(**_route_annotations())
        .order_by("-total")[offset:offset + limit]
    )
    career_ids = [r["career_id"] for r in career_rows]
    by_career = {}
    if career_ids:
        user_rows = (
            qs.filter(career_id__in=career_ids, user__isnull=False)
            .values("career_id", "user_id", "user__username", "user__email")
            .annotate(last_at=Max("created_at"), **_route_annotations())
            .order_by("career_id", "-total")
        )
        for u in user_rows:
            by_career.setdefault(u["career_id"], []).append(
                {
                    "user_id": u["user_id"],
                    "username": u["user__username"],
                    "email": u["user__email"],
                    "course": u["course"],
                    "apprenticeship": u["apprenticeship"],
                    "job": u["job"],
                    "total": u["total"],
                    "last_at": u["last_at"].isoformat() if u["last_at"] else None,
                }
            )
    results = [
        {
            "career_id": r["career_id"],
            "jobname": r["career__jobname"],
            "course": r["course"],
            "apprenticeship": r["apprenticeship"],
            "job": r["job"],
            "total": r["total"],
            "users": by_career.get(r["career_id"], [])[:users_per_career],
        }
        for r in career_rows
    ]
    return {"total": total, "results": results}


def provider_clicks(offset=0, limit=10, date_from=None, date_to=None):
    """Most-clicked provider links (provider name in activity_value), ranked."""
    qs = UserActivity.objects.filter(
        activity_type__in=[C.PROVIDER_LINK_CLICKED, C.CONNECT_BUTTON_CLICKED]
    ).exclude(activity_value__isnull=True).exclude(activity_value="")
    qs = _range(qs, "created_at", date_from, date_to)
    total = qs.values("activity_value").distinct().count()
    rows = (
        qs.values("activity_value")
        .annotate(count=Count("id"))
        .order_by("-count")[offset:offset + limit]
    )
    return {"total": total, "results": [{"provider": r["activity_value"], "count": r["count"]} for r in rows]}


def _provider_cards_base(date_from=None, date_to=None):
    """Provider/connect clicks that reference a titled card (course/app/job)."""
    qs = UserActivity.objects.filter(
        activity_type__in=[C.PROVIDER_LINK_CLICKED, C.CONNECT_BUTTON_CLICKED]
    ).exclude(card__isnull=True).exclude(card="")
    qs = _range(qs, "created_at", date_from, date_to)
    return qs


def provider_cards(offset=0, limit=10, date_from=None, date_to=None):
    """
    Titled cards (course/apprenticeship/job) ranked by clicks. Each row is one
    (card title, career, route). Powers the "Provider Link Clicks by Title" table.
    Returns {total, results:[{card, career_id, jobname, route_id, clicks}]}.
    """
    qs = _provider_cards_base(date_from, date_to)
    total = qs.values("card", "career_id", "route_id").distinct().count()
    rows = (
        qs.values("card", "career_id", "career__jobname", "route_id")
        .annotate(clicks=Count("id"))
        .order_by("-clicks")[offset:offset + limit]
    )
    return {
        "total": total,
        "results": [
            {
                "card": r["card"],
                "career_id": r["career_id"],
                "jobname": r["career__jobname"],
                "route_id": r["route_id"],
                "clicks": r["clicks"],
            }
            for r in rows
        ],
    }


def card_click_users(card, career_id=None, route=None, date_from=None, date_to=None, users_limit=2000):
    """
    Users who clicked one titled card, each with their click count. Powers the
    lazy hover popup on the titles table. One query.
    Returns {card, career_id, jobname, route_id, clicks, users:[...]}.
    """
    qs = _provider_cards_base(date_from, date_to).filter(card=card)
    if career_id:
        qs = qs.filter(career_id=career_id)
    if route:
        qs = qs.filter(route_id=route)

    rows = qs.values(
        "user_id", "user__username", "user__email", "career__jobname", "route_id"
    ).annotate(clicks=Count("id"), last_at=Max("created_at"))

    name, route_val, total, users = None, route, 0, []
    for r in rows:
        name = name or r["career__jobname"]
        route_val = route_val or r["route_id"]
        total += r["clicks"]
        if r["user_id"] is not None:
            users.append(
                {
                    "user_id": r["user_id"],
                    "username": r["user__username"],
                    "email": r["user__email"],
                    "clicks": r["clicks"],
                    "last_at": r["last_at"].isoformat() if r["last_at"] else None,
                }
            )
    users.sort(key=lambda u: u["clicks"], reverse=True)
    return {
        "card": card,
        "career_id": career_id,
        "jobname": name,
        "route_id": route_val,
        "clicks": total,
        "users": users[:users_limit],
    }


def provider_card_users(offset=0, limit=10, date_from=None, date_to=None, users_per_card=2000):
    """
    Every titled card with the users who clicked it. Powers the grouped "View all"
    sheet / PDF. Single group-by (card, career, route, user) query.
    Returns {total, results:[{card, career_id, jobname, route_id, clicks, users:[...]}]}.
    """
    rows = _provider_cards_base(date_from, date_to).values(
        "card", "career_id", "career__jobname", "route_id",
        "user_id", "user__username", "user__email",
    ).annotate(clicks=Count("id"), last_at=Max("created_at"))

    cards = {}
    for r in rows:
        key = (r["card"], r["career_id"], r["route_id"])
        c = cards.get(key)
        if c is None:
            c = cards[key] = {
                "card": r["card"],
                "career_id": r["career_id"],
                "jobname": r["career__jobname"],
                "route_id": r["route_id"],
                "clicks": 0,
                "users": [],
            }
        c["clicks"] += r["clicks"]
        if r["user_id"] is not None:
            c["users"].append(
                {
                    "user_id": r["user_id"],
                    "username": r["user__username"],
                    "email": r["user__email"],
                    "clicks": r["clicks"],
                    "last_at": r["last_at"].isoformat() if r["last_at"] else None,
                }
            )
    out = sorted(cards.values(), key=lambda c: c["clicks"], reverse=True)
    for c in out:
        c["users"].sort(key=lambda u: u["clicks"], reverse=True)
        c["users"] = c["users"][:users_per_card]
    total = len(out)
    if offset or limit < total:
        out = out[offset:offset + limit]
    return {"total": total, "results": out}


def consent_leads(offset=0, limit=10, date_from=None, date_to=None):
    """Careers generating consent leads (from the ProviderLead table), ranked."""
    base = ProviderLead.objects.filter(career__isnull=False)
    base = _range(base, "consent_at", date_from, date_to)
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


def career_lead_users(career_id, date_from=None, date_to=None, users_limit=2000):
    """
    Users who generated consent leads for one career, each with their lead count.
    Powers the lazy hover popup on the Careers Generating Leads table. One query.
    Returns {career_id, jobname, leads, users:[...]}.
    """
    qs = ProviderLead.objects.filter(career_id=career_id)
    qs = _range(qs, "consent_at", date_from, date_to)

    rows = qs.values(
        "user_id", "user__username", "user__email", "career__jobname"
    ).annotate(leads=Count("id"), last_at=Max("consent_at"))

    name, total, users = None, 0, []
    for r in rows:
        name = name or r["career__jobname"]
        total += r["leads"]
        if r["user_id"] is not None:
            users.append(
                {
                    "user_id": r["user_id"],
                    "username": r["user__username"],
                    "email": r["user__email"],
                    "leads": r["leads"],
                    "last_at": r["last_at"].isoformat() if r["last_at"] else None,
                }
            )
    users.sort(key=lambda u: u["leads"], reverse=True)
    if name is None:
        name = Career.objects.filter(id=career_id).values_list("jobname", flat=True).first()
    return {"career_id": career_id, "jobname": name, "leads": total, "users": users[:users_limit]}


def lead_engagement_users(offset=0, limit=10, date_from=None, date_to=None, users_per_career=2000):
    """
    Careers ranked by consent leads, each with the users who generated them.
    Powers the grouped "View all" sheet / PDF. Single group-by (career, user) query.
    Returns {total, results:[{career_id, jobname, leads, users:[...]}]}.
    """
    qs = ProviderLead.objects.filter(career__isnull=False)
    qs = _range(qs, "consent_at", date_from, date_to)

    rows = qs.values(
        "career_id", "career__jobname", "user_id", "user__username", "user__email"
    ).annotate(leads=Count("id"), last_at=Max("consent_at"))

    careers = {}
    for r in rows:
        c = careers.get(r["career_id"])
        if c is None:
            c = careers[r["career_id"]] = {
                "career_id": r["career_id"],
                "jobname": r["career__jobname"],
                "leads": 0,
                "users": [],
            }
        c["leads"] += r["leads"]
        if r["user_id"] is not None:
            c["users"].append(
                {
                    "user_id": r["user_id"],
                    "username": r["user__username"],
                    "email": r["user__email"],
                    "leads": r["leads"],
                    "last_at": r["last_at"].isoformat() if r["last_at"] else None,
                }
            )
    out = sorted(careers.values(), key=lambda c: c["leads"], reverse=True)
    for c in out:
        c["users"].sort(key=lambda u: u["leads"], reverse=True)
        c["users"] = c["users"][:users_per_career]
    total = len(out)
    if offset or limit < total:
        out = out[offset:offset + limit]
    return {"total": total, "results": out}


def timeseries(activity_type=None, date_from=None, date_to=None):
    """User activity by date (for trend charts). All-time when no range given."""
    qs = UserActivity.objects.all()
    qs = _range(qs, "created_at", date_from, date_to)
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
    # .values(...) BEFORE annotate so we select only these 4 columns — NOT full
    # Career model rows, which would drag the wide scraped TextFields across the
    # wire (huge for a 2,415-row PDF export).
    qs = (
        base.values("id", "jobname", "career_type", "sub_type")
        .annotate(event_count=Count("activities", filter=act_q))
        .order_by("-event_count", "jobname")[offset:offset + limit]
    )
    results = [
        {
            "id": r["id"],
            "jobname": r["jobname"],
            "career_type": r["career_type"],
            "sub_type": r["sub_type"],
            "event_count": r["event_count"],
        }
        for r in qs
    ]
    return {"total": total, "results": results}


def events_list(activity_types=None, q=None, date_from=None, date_to=None, offset=0, limit=50):
    """
    Paginated flat event feed for drill-downs from the KPI cards. Each row
    carries the career acted on plus the user (username/email) and event
    details. Optional filter by activity_types (list), search (q over
    user/career), and date range. Returns {total, results}.
    """
    qs = UserActivity.objects.all()
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
    # One query selecting only the columns needed. The auth_user and careerjob
    # joins are cheap when we pull just username/email/jobname — NOT select_related,
    # which would drag the wide scraped career row (big TextFields) across the wire.
    page = qs.order_by("-created_at").values(
        "created_at", "activity_type", "career_id", "career__jobname", "user_id",
        "user__username", "user__email", "route_id", "activity_value",
    )[offset:offset + limit]
    rows = [
        {
            "created_at": r["created_at"].isoformat(),
            "activity_type": r["activity_type"],
            "career_id": r["career_id"],
            "career": r["career__jobname"],
            "user_id": r["user_id"],
            "username": r["user__username"],
            "email": r["user__email"],
            "route_id": r["route_id"],
            "activity_value": r["activity_value"],
        }
        for r in page
    ]
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
    Paginated list of users. The date range filters by REGISTRATION date
    (date_joined) — i.e. "users who joined within [date_from, date_to]" — so the
    returned `total` answers how many users there were in that window. Optional
    search (q). Ordered by most active first. Returns {total, results}.
    """
    base = User.objects.all()
    if q:
        base = base.filter(Q(username__icontains=q) | Q(email__icontains=q))
    if date_from:
        base = base.filter(date_joined__date__gte=date_from)
    if date_to:
        base = base.filter(date_joined__date__lte=date_to)

    total = base.count()
    qs = base.annotate(
        event_count=Count("activities"),
        last_active=Max("activities__created_at"),
    ).order_by("-event_count", "username")[offset:offset + limit]

    results = [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "event_count": u.event_count,
            "last_active": u.last_active.isoformat() if u.last_active else None,
            "date_joined": u.date_joined.isoformat() if u.date_joined else None,
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
    # Select only the columns we need in ONE query. NOT select_related("career"),
    # which would fetch every column of the wide scraped CareerJob table (several
    # big TextFields) per row. Joining for just career__jobname is cheap.
    rows = qs.order_by("-created_at").values(
        "activity_type", "career_id", "route_id", "activity_value",
        "created_at", "career__jobname",
    )[:timeline_limit]
    timeline = [
        {
            "activity_type": r["activity_type"],
            "career_id": r["career_id"],
            "career": r["career__jobname"],
            "route_id": r["route_id"],
            "activity_value": r["activity_value"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
    info = User.objects.filter(id=user_id).values("username", "email").first() or {}
    return {
        "user_id": user_id,
        "username": info.get("username"),
        "email": info.get("email"),
        # by_type already groups every event for this user, so its sum is the
        # total — no need for a separate count() round-trip to the remote DB.
        "total_events": sum(by_type.values()),
        "counts": by_type,
        "timeline": timeline,
    }


def popular_careers_by_location(offset=0, limit=10, date_from=None, date_to=None):
    """
    Cities ranked by career views, each with its single most-viewed career.
    Paginated by city. Location is read at query time from UserProfile.city
    (joined via the event's user); anonymised/deleted-user rows are excluded.
    Returns {total, results:[{city, jobname, count, city_views}]}.
    """
    city_field = "user__userprofile__city"
    # One group-by (city, career) query, folded in Python to get each city's view
    # total AND its single most-viewed career. Avoids the old N+1 (a separate
    # "top career" query per city — ~10 round-trips to the remote DB).
    rows = _city_views_base(date_from, date_to).values(
        city_field, "career_id", "career__jobname"
    ).annotate(count=Count("id"))

    city_views, top = {}, {}
    for r in rows:
        city = r[city_field]
        city_views[city] = city_views.get(city, 0) + r["count"]
        if city not in top or r["count"] > top[city][0]:
            top[city] = (r["count"], r["career__jobname"])

    ordered = sorted(city_views.items(), key=lambda kv: kv[1], reverse=True)
    total = len(ordered)
    results = [
        {
            "city": city,
            "jobname": top[city][1],
            "count": top[city][0],
            "city_views": views,
        }
        for city, views in ordered[offset:offset + limit]
    ]
    return {"total": total, "results": results}


def searched_careers(offset=0, limit=10, date_from=None, date_to=None):
    """
    Careers searched by users, each paired with the location they searched in.
    The searched city is read from the event's activity_value (set by the
    frontend at search time). One row per (career, city), ranked by search count
    (most-searched first, to match the other ranked tables).
    Returns {total, results:[{career_id, jobname, city, count}]}.
    """
    base = (
        UserActivity.objects.filter(
            activity_type=C.SEARCHED_CAREER, career__isnull=False
        )
        .exclude(activity_value__isnull=True)
        .exclude(activity_value="")
    )
    base = _range(base, "created_at", date_from, date_to)

    rows = list(
        base.values("career_id", "career__jobname", "activity_value")
        .annotate(count=Count("id"))
        .order_by("-count", "career__jobname")
    )
    total = len(rows)
    results = [
        {
            "career_id": r["career_id"],
            "jobname": r["career__jobname"],
            "city": r["activity_value"],
            "count": r["count"],
        }
        for r in rows[offset:offset + limit]
    ]
    return {"total": total, "results": results}


def _searched_base(date_from=None, date_to=None):
    """searched_career events with a career and a non-empty searched location."""
    base = (
        UserActivity.objects.filter(
            activity_type=C.SEARCHED_CAREER, career__isnull=False
        )
        .exclude(activity_value__isnull=True)
        .exclude(activity_value="")
    )
    return _range(base, "created_at", date_from, date_to)


def searched_career_users(career_id, city, date_from=None, date_to=None, users_limit=2000):
    """
    Users who searched one career in one location, with how many times each did.
    Powers the lazy hover popup on the Searched Careers table.
    Single query. Returns {career_id, city, count, users:[...]}.
    """
    rows = list(
        _searched_base(date_from, date_to)
        .filter(career_id=career_id, activity_value=city)
        .exclude(user__isnull=True)
        .values("user_id", "user__username", "user__email")
        .annotate(count=Count("id"), last_at=Max("created_at"))
    )
    users = sorted(
        (
            {
                "user_id": r["user_id"],
                "username": r["user__username"],
                "email": r["user__email"],
                "count": r["count"],
                "last_at": r["last_at"].isoformat() if r["last_at"] else None,
            }
            for r in rows
        ),
        key=lambda u: u["count"],
        reverse=True,
    )
    return {
        "career_id": career_id,
        "city": city,
        "count": sum(r["count"] for r in rows),
        "users": users[:users_limit],
    }


def searched_career_engagement_users(offset=0, limit=10, date_from=None, date_to=None, users_per_group=2000):
    """
    (career, city) pairs ranked by search count, each with the users who searched
    it (and how many times). Powers the grouped "View all" sheet / PDF for the
    Searched Careers section. Single group-by (career, city, user) query.
    Returns {total, results:[{career_id, jobname, city, count, users:[...]}]}.
    """
    rows = (
        _searched_base(date_from, date_to)
        .values("career_id", "career__jobname", "activity_value",
                "user_id", "user__username", "user__email")
        .annotate(count=Count("id"), last_at=Max("created_at"))
    )
    groups = {}
    for r in rows:
        key = (r["career_id"], r["activity_value"])
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "career_id": r["career_id"],
                "jobname": r["career__jobname"],
                "city": r["activity_value"],
                "count": 0,
                "users": [],
            }
        g["count"] += r["count"]
        if r["user_id"] is not None:
            g["users"].append(
                {
                    "user_id": r["user_id"],
                    "username": r["user__username"],
                    "email": r["user__email"],
                    "count": r["count"],
                    "last_at": r["last_at"].isoformat() if r["last_at"] else None,
                }
            )
    out = sorted(groups.values(), key=lambda g: g["count"], reverse=True)
    for g in out:
        g["users"].sort(key=lambda u: u["count"], reverse=True)
        g["users"] = g["users"][:users_per_group]
    total = len(out)
    if offset or limit < total:
        out = out[offset:offset + limit]
    return {"total": total, "results": out}


def _city_views_base(date_from=None, date_to=None):
    """Career-view events with an identifiable user city (shared by the two below)."""
    base = (
        UserActivity.objects.filter(activity_type=C.CAREER_VIEWED, career__isnull=False)
        .exclude(user__isnull=True)
        .exclude(user__userprofile__city__isnull=True)
        .exclude(user__userprofile__city="")
    )
    base = _range(base, "created_at", date_from, date_to)
    return base


def city_users(city, date_from=None, date_to=None, users_limit=2000):
    """
    Users whose profile city is `city`, with how many careers each has viewed.
    Powers the lazy hover popup on the Popular Careers by Location table.
    Single query. Returns {city, city_views, users:[...]}.
    """
    rows = list(
        _city_views_base(date_from, date_to)
        .filter(user__userprofile__city=city)
        .values("user_id", "user__username", "user__email")
        .annotate(count=Count("id"), last_at=Max("created_at"))
    )
    users = sorted(
        (
            {
                "user_id": r["user_id"],
                "username": r["user__username"],
                "email": r["user__email"],
                "count": r["count"],
                "last_at": r["last_at"].isoformat() if r["last_at"] else None,
            }
            for r in rows
        ),
        key=lambda u: u["count"],
        reverse=True,
    )
    return {
        "city": city,
        "city_views": sum(r["count"] for r in rows),
        "users": users[:users_limit],
    }


def location_engagement_users(offset=0, limit=10, date_from=None, date_to=None, users_per_city=2000):
    """
    Cities ranked by career views, each with the users living there (and how many
    careers each viewed). Powers the grouped "View all" sheet / PDF for the
    Popular Careers by Location section. Single group-by (city, user) query.
    Returns {total, results:[{city, city_views, users:[...]}]}.
    """
    rows = (
        _city_views_base(date_from, date_to)
        .values("user__userprofile__city", "user_id", "user__username", "user__email")
        .annotate(count=Count("id"), last_at=Max("created_at"))
    )
    cities = {}
    for r in rows:
        city = r["user__userprofile__city"]
        c = cities.get(city)
        if c is None:
            c = cities[city] = {"city": city, "city_views": 0, "users": []}
        c["city_views"] += r["count"]
        c["users"].append(
            {
                "user_id": r["user_id"],
                "username": r["user__username"],
                "email": r["user__email"],
                "count": r["count"],
                "last_at": r["last_at"].isoformat() if r["last_at"] else None,
            }
        )
    out = sorted(cities.values(), key=lambda c: c["city_views"], reverse=True)
    for c in out:
        c["users"].sort(key=lambda u: u["count"], reverse=True)
        c["users"] = c["users"][:users_per_city]
    total = len(out)
    if offset or limit < total:
        out = out[offset:offset + limit]
    return {"total": total, "results": out}
