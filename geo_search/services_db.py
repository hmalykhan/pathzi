import math
from typing import List, Tuple, Optional, Dict

from django.apps import apps
from django.db.models import Avg, Count

TYPE_TO_MODEL = {
    "jobs": ("jobs", "Job"),
    "courses": ("courses", "Course"),
    "apprenticeships": ("apprenticeship", "Apprenticeship"),
}

def get_models_for_types(types: List[str]):
    out = []
    for t in types:
        app_label, model_name = TYPE_TO_MODEL[t]
        out.append(apps.get_model(app_label, model_name))
    return out

def db_suggest_distinct(field: str, text: str, types: List[str], limit: int = 8) -> List[Dict]:
    """
    Autocomplete suggestions from DB (prefix first, fallback contains).
    field: 'city' or 'zip_code'
    
    OPTIMIZED: Uses UNION queries to fetch from all models in a single database round-trip.
    """
    models = get_models_for_types(types)
    text = (text or "").strip()
    if not text or not models:
        return []

    # Helper to build a queryset for a single model
    def build_qs(model, lookup_type):
        return (
            model.objects
            .exclude(**{f"{field}__isnull": True})
            .exclude(**{field: ""})
            .filter(**{f"{field}__{lookup_type}": text})
            .values_list(field, flat=True)
            .distinct()
            .order_by(field)[:limit * 2]  # Get extra to allow deduplication
        )

    # Phase 1: Try prefix match (istartswith) with UNION
    prefix_qs = None
    for M in models:
        qs = build_qs(M, "istartswith")
        if prefix_qs is None:
            prefix_qs = qs
        else:
            prefix_qs = prefix_qs.union(qs)
    
    # Execute and deduplicate
    seen = set()
    out = []
    
    if prefix_qs:
        for v in prefix_qs:
            v = (v or "").strip()
            if not v:
                continue
            key = v.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "kind": "city" if field == "city" else "postcode",
                "label": v,
                "value": v,
            })
            if len(out) >= limit:
                return out

    # Phase 2: Fallback to contains match (icontains) if prefix didn't yield results
    if not out:
        contains_qs = None
        for M in models:
            qs = build_qs(M, "icontains")
            if contains_qs is None:
                contains_qs = qs
            else:
                contains_qs = contains_qs.union(qs)
        
        if contains_qs:
            for v in contains_qs:
                v = (v or "").strip()
                if not v:
                    continue
                key = v.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "kind": "city" if field == "city" else "postcode",
                    "label": v,
                    "value": v,
                })
                if len(out) >= limit:
                    return out

    return out


def db_list_distinct_with_counts(field: str, types: List[str], q: str = "", limit: int = 500) -> List[Dict]:
    """
    Full list endpoint: returns distinct values + counts (merged across types).
    field: 'city' or 'zip_code'
    """
    models = get_models_for_types(types)
    q = (q or "").strip()
    limit = min(max(int(limit), 1), 5000)

    merged = {}  # key -> {"value": v, "count": n}
    for M in models:
        qs = M.objects.exclude(**{f"{field}__isnull": True}).exclude(**{field: ""})
        if q:
            qs = qs.filter(**{f"{field}__icontains": q})

        qs = (
            qs.values(field)
            .annotate(n=Count("id"))
            .order_by("-n")[:limit]
        )

        for row in qs:
            v = (row.get(field) or "").strip()
            if not v:
                continue
            key = v.lower()
            if key not in merged:
                merged[key] = {"value": v, "count": 0}
            merged[key]["count"] += int(row.get("n") or 0)

    # sort by count desc, then alpha
    items = sorted(merged.values(), key=lambda x: (-x["count"], x["value"].lower()))
    items = items[:limit]

    kind = "city" if field == "city" else "postcode"
    return [{"kind": kind, "value": x["value"], "count": x["count"]} for x in items]

def weighted_centroid_for_city_or_postcode(
    city: Optional[str],
    postcode: Optional[str],
    types: List[str],
) -> Optional[Tuple[float, float]]:
    """
    Returns centroid (lat, lon) from DB rows across selected types.
    Weighted by row counts per table.
    """
    models = get_models_for_types(types)

    city = (city or "").strip()
    postcode = (postcode or "").strip()

    total_count = 0
    sum_lat = 0.0
    sum_lon = 0.0

    for M in models:
        qs = M.objects.exclude(latitude__isnull=True).exclude(longitude__isnull=True)
        if city:
            qs = qs.filter(city__iexact=city)
        if postcode:
            qs = qs.filter(zip_code__iexact=postcode)

        agg = qs.aggregate(c=Count("id"), lat=Avg("latitude"), lon=Avg("longitude"))
        c = int(agg["c"] or 0)
        lat = agg["lat"]
        lon = agg["lon"]

        if c > 0 and lat is not None and lon is not None:
            total_count += c
            sum_lat += float(lat) * c
            sum_lon += float(lon) * c

    if total_count == 0:
        return None

    return (sum_lat / total_count, sum_lon / total_count)

def bbox_for_radius_km(lat: float, lon: float, radius_km: float):
    delta_lat = radius_km / 111.0
    lat_rad = math.radians(lat)
    cos_lat = max(math.cos(lat_rad), 0.000001)
    delta_lon = radius_km / (111.0 * cos_lat)
    return (lat - delta_lat, lat + delta_lat, lon - delta_lon, lon + delta_lon)
