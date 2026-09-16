"""
Nearest-first lookup for the routes into a career (jobs / courses /
apprenticeships), with the distance from a location to each item.

The location is, in order: lat/lng or a postcode sent with the request, the
user's active saved coordinate, the legacy lat/lng on the profile, or the
centre of the user's city. The scraper tables carry latitude/longitude on
~95-99% of rows, so instead of an exact `city == profile.city` match (which
returns nothing for a user in a suburb or the next town over) we search a
radius around that location and order by distance.
"""
import logging
import re
from typing import Optional, Tuple

from django.core.cache import cache
from django.db.models import Avg, Count, F, FloatField, Q
from django.db.models.expressions import RawSQL
from django.db.models.functions import Lower

from accounts.models import Coordinates
from apprenticeship.models import Apprenticeship
from courses.models import Course
from geo_search.services_db import weighted_centroid_for_city_or_postcode
from geo_search.services_search import HAVERSINE_SQL
from geo_search.utils import UK_POSTCODE_RE
from jobs.models import Job

logger = logging.getLogger(__name__)

KM_PER_MILE = 1.609344
DEFAULT_RADIUS_MILES = 25.0
MIN_RADIUS_MILES = 1.0
MAX_RADIUS_MILES = 200.0

CENTROID_TTL = 60 * 60 * 24  # a city or postcode doesn't move
ROUTE_TYPES = ["courses", "jobs", "apprenticeships"]
ROUTE_MODELS = (Course, Job, Apprenticeship)
OUTWARD_CODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?$")  # district only: "M1", "B15", "SW1A"


class PostcodeNotFound(Exception):
    """A postcode was sent with the request but couldn't be placed."""


def _param(request, *names):
    """
    First non-empty value for any of `names`, from the body then the query
    string.

    Reads both through getattr: a DRF request always has .data and
    .query_params, but a plain Django request has neither, and this should
    degrade to "no value" rather than raise.
    """
    data = getattr(request, "data", None)
    if not hasattr(data, "get"):
        data = {}
    params = getattr(request, "query_params", None)
    if not hasattr(params, "get"):
        params = getattr(request, "GET", {})

    for name in names:
        for source in (data, params):
            value = source.get(name)
            if value not in (None, ""):
                return value
    return None


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _valid(lat, lon) -> bool:
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180


def _key(*parts) -> str:
    """Cache key without spaces (they break memcached-style key rules)."""
    return ":".join(re.sub(r"\s+", "_", str(part).strip().lower()) for part in parts)


def _cached(key, compute):
    """
    Cache a centroid (or its absence) for a day. The cache is only an
    optimisation: a Redis outage must not fail the request.
    """
    try:
        cached = cache.get(key)
    except Exception:
        logger.warning("centroid cache read failed", exc_info=True)
        cached = None
    if cached is not None:
        return tuple(cached) if cached else None

    value = compute()
    try:
        # Cache misses too (as False) so an unknown place doesn't rescan every request.
        cache.set(key, list(value) if value else False, timeout=CENTROID_TTL)
    except Exception:
        logger.warning("centroid cache write failed", exc_info=True)
    return value


def city_centroid(city: str) -> Optional[Tuple[float, float]]:
    """Centre of a city, averaged from the scraped rows in it."""
    return _cached(
        _key("careers", "city_centroid", "v1", city),
        lambda: weighted_centroid_for_city_or_postcode(city, None, ROUTE_TYPES),
    )


def _rows_centroid(**filters) -> Optional[Tuple[float, float]]:
    """Average position of the located rows matching `filters`, across all three tables."""
    total, lat_sum, lon_sum = 0, 0.0, 0.0
    for M in ROUTE_MODELS:
        agg = (
            M.objects.filter(latitude__isnull=False, longitude__isnull=False, **filters)
            .aggregate(c=Count("id"), lat=Avg("latitude"), lon=Avg("longitude"))
        )
        if agg["c"]:
            total += agg["c"]
            lat_sum += float(agg["lat"]) * agg["c"]
            lon_sum += float(agg["lon"]) * agg["c"]
    return (lat_sum / total, lon_sum / total) if total else None


def normalize_postcode(value) -> str:
    """'b55sl' or ' B5  5SL ' -> 'B5 5SL'; 'm1' -> 'M1'; '' if it isn't a UK postcode."""
    compact = re.sub(r"\s+", "", str(value or "")).upper()
    if OUTWARD_CODE_RE.match(compact):
        return compact
    if UK_POSTCODE_RE.match(compact):
        return f"{compact[:-3]} {compact[-3:]}"
    return ""


def postcode_centroid(postcode: str) -> Optional[Tuple[float, float]]:
    """
    Where a (normalised) postcode is, from the scraped rows: the exact postcode
    if any row has it, otherwise the centre of its district ("B5 5SL" -> "B5").
    Stored postcodes are 96-99% in the clean "AB1 2CD" form, so both lookups
    are plain matches on the zip_code index.
    """
    def compute():
        if " " in postcode:
            exact = _rows_centroid(zip_code=postcode)
            if exact:
                return exact
        district = postcode.split(" ")[0]
        return _rows_centroid(zip_code__startswith=district + " ")

    return _cached(_key("careers", "postcode_centroid", "v1", postcode), compute)


def requested_origin(request) -> Optional[Tuple[float, float]]:
    """
    A location sent with the request, which overrides the user's own:
    `lat` + `lng`, or `postcode`. None if neither was sent.
    Raises PostcodeNotFound when a postcode is sent but can't be placed.
    """
    lat = _to_float(_param(request, "lat", "latitude"))
    lon = _to_float(_param(request, "lng", "lon", "longitude"))
    if _valid(lat, lon):
        return lat, lon

    raw = _param(request, "postcode", "postal_code", "zip_code")
    if raw is None:
        return None
    postcode = normalize_postcode(raw)
    origin = postcode_centroid(postcode) if postcode else None
    if origin is None:
        raise PostcodeNotFound(raw)
    return origin


def saved_origin(*, profile=None, city: str = "") -> Optional[Tuple[float, float]]:
    """
    The user's own location: their active saved coordinate, then the legacy
    lat/lng on the profile, then the centre of their city. None if unknown.
    """
    if profile is not None:
        # Read the active coordinate directly: profile.lat/lng is only synced
        # when a coordinate is saved, so most profiles don't have it.
        coord = (
            Coordinates.objects
            .filter(
                user_profile=profile,
                active=True,
                latitude__isnull=False,
                longitude__isnull=False,
            )
            .order_by("-id")
            .values_list("latitude", "longitude")
            .first()
        )
        if coord and _valid(*coord):
            return float(coord[0]), float(coord[1])

        lat, lon = _to_float(profile.lat), _to_float(profile.lng)
        if _valid(lat, lon):
            return lat, lon

    if city:
        return city_centroid(city)
    return None


def parse_radius_miles(request) -> float:
    radius = _to_float(_param(request, "radius_miles"))
    if radius is None:
        return DEFAULT_RADIUS_MILES
    return min(max(radius, MIN_RADIUS_MILES), MAX_RADIUS_MILES)


def nearest_route_items(Model, *, jobname: str, lat: float, lon: float,
                        radius_miles: float, city: str = ""):
    """
    Items for this career within `radius_miles` of (lat, lon), nearest first,
    each annotated with `distance_km`.

    Rows without coordinates can't be placed; the ones in `city` (the user's
    own city) are kept and sorted last with no distance.
    """
    qs = (
        Model.objects
        .alias(sub_l=Lower("subcategory"))  # uses the lower(subcategory) index
        .filter(sub_l=jobname.strip().lower())
        .annotate(distance_km=RawSQL(HAVERSINE_SQL, (lat, lat, lon), output_field=FloatField()))
    )

    in_range = Q(distance_km__lte=radius_miles * KM_PER_MILE)
    if city:
        qs = qs.alias(city_l=Lower("city"))
        in_range |= Q(distance_km__isnull=True, city_l=city.strip().lower())

    return qs.filter(in_range).order_by(F("distance_km").asc(nulls_last=True), "-id")


def attach_distances(rows, items):
    """Add distance_km / distance_miles to serialized rows (same order as items)."""
    for row, item in zip(rows, items):
        km = getattr(item, "distance_km", None)
        row["distance_km"] = round(km, 2) if km is not None else None
        row["distance_miles"] = round(km / KM_PER_MILE, 1) if km is not None else None
    return rows

# --------------------------------------------------------------------------
# Relevance ranking (#26)
# --------------------------------------------------------------------------
# Nearest-first is the default and stays the default. Distance alone is a
# poor guide when the nearest course is "Construction (General)" and one a
# few miles further is "Carpentry and Joinery Level 2" - the second is what
# the student actually wants. Relevance blends three things, and is only
# used when the app asks for it with ?sort=relevance.

RELEVANCE_TITLE_WEIGHT = 0.50
RELEVANCE_DISTANCE_WEIGHT = 0.35
RELEVANCE_DETAIL_WEIGHT = 0.15

# Words that appear in nearly every title and say nothing about the match.
_STOPWORDS = {
    "and", "or", "the", "of", "in", "for", "with", "to", "a", "an",
    "level", "diploma", "certificate", "award", "course", "training",
    "apprentice", "apprenticeship", "job", "vacancy", "full", "part", "time",
}


def _words(text):
    return {w for w in re.split(r"[^a-z0-9]+", (text or "").lower())
            if w and w not in _STOPWORDS and len(w) > 2}


def _title_of(item):
    for attr in ("course_name", "title", "jobname", "name", "subcategory"):
        value = getattr(item, attr, None)
        if value:
            return str(value)
    return ""


def _detail_score(item):
    """Prefer rows a student can actually act on over near-empty stubs."""
    score = 0.0
    for attr in ("entry_reeq", "requirement_summery", "essential_qualifications",
                 "skills_youll_need", "course_description", "summary_text"):
        value = getattr(item, attr, None)
        if isinstance(value, (list, tuple)):
            value = " ".join(str(v) for v in value)
        if value and str(value).strip():
            score += 0.5
    return min(score, 1.0)


def relevance_score(item, career_words, radius_km):
    """
    0 to 1. Higher is a better card to show first.

    Kept deliberately simple and explainable: a weighted blend of how well
    the title matches the career, how close it is, and whether the row has
    enough detail to be useful.
    """
    title_words = _words(_title_of(item))
    if career_words and title_words:
        overlap = len(career_words & title_words) / len(career_words)
    else:
        overlap = 0.0

    km = getattr(item, "distance_km", None)
    if km is None or not radius_km:
        # No coordinates: don't reward or punish, sit mid-table.
        distance = 0.5
    else:
        distance = max(0.0, 1.0 - (km / radius_km))

    return (RELEVANCE_TITLE_WEIGHT * overlap
            + RELEVANCE_DISTANCE_WEIGHT * distance
            + RELEVANCE_DETAIL_WEIGHT * _detail_score(item))


def wants_relevance(request) -> bool:
    """True only when the app explicitly asks. Distance stays the default."""
    value = (_param(request, "sort", "order_by") or "").strip().lower()
    return value in ("relevance", "relevant", "best")


def rank_by_relevance(items, *, jobname: str, radius_miles: float):
    """
    Re-order already-fetched items, best match first.

    Works on the list the database already returned, so it adds no query.
    Distance remains the tie-breaker, which keeps the order stable.
    """
    career_words = _words(jobname)
    radius_km = (radius_miles or 0) * KM_PER_MILE

    def sort_key(item):
        km = getattr(item, "distance_km", None)
        return (-relevance_score(item, career_words, radius_km),
                km if km is not None else float("inf"))

    ranked = sorted(items, key=sort_key)
    for item in ranked:
        item.relevance = round(relevance_score(item, career_words, radius_km), 3)
    return ranked


def attach_relevance(rows, items):
    """Expose the score so the app (and we) can see why an order came out."""
    for row, item in zip(rows, items):
        score = getattr(item, "relevance", None)
        if score is not None:
            row["relevance"] = score
    return rows
