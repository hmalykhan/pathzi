from typing import Dict, List, Any
from django.apps import apps
from django.db.models import Q
from django.db.models.expressions import RawSQL

from .services_db import bbox_for_radius_km, TYPE_TO_MODEL

HAVERSINE_SQL = """
(6371 * 2 * ASIN(SQRT(
    POWER(SIN(RADIANS(latitude - %s) / 2), 2) +
    COS(RADIANS(%s)) * COS(RADIANS(latitude)) *
    POWER(SIN(RADIANS(longitude - %s) / 2), 2)
)))
"""

def _model_for_type(t: str):
    app_label, model_name = TYPE_TO_MODEL[t]
    return apps.get_model(app_label, model_name)

def _keyword_filter_for_type(t: str, q: str) -> Q:
    q = (q or "").strip()
    if not q:
        return Q()

    if t == "jobs":
        return Q(title__icontains=q) | Q(company__icontains=q) | Q(location__icontains=q)
    if t == "courses":
        return Q(course_name__icontains=q) | Q(college_name__icontains=q) | Q(address__icontains=q)
    if t == "apprenticeships":
        return (
            Q(title__icontains=q) |
            Q(employer_name__icontains=q) |
            Q(location_summary__icontains=q) |
            Q(where_youll_work_address__icontains=q)
        )
    return Q()

def _fields_for_type(t: str) -> List[str]:
    if t == "jobs":
        return ["job_id","title","company","location","job_url","apply_url","image_url","category","subcategory","city","zip_code","state","latitude","longitude"]
    if t == "courses":
        return ["course_id","course_name","college_name","address","course_url","image_url","category","subcategory","city","zip_code","state","latitude","longitude"]
    if t == "apprenticeships":
        return ["vacancy_ref","title","employer_name","location_summary","vacancy_url","image_url","category","subcategory","city","zip_code","state","latitude","longitude"]
    return ["id","latitude","longitude"]

def search_nearby(
    t: str,
    lat: float,
    lon: float,
    radius_km: float,
    q: str = "",
    category: str = "",
    subcategory: str = "",
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    M = _model_for_type(t)
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), 100)

    min_lat, max_lat, min_lon, max_lon = bbox_for_radius_km(lat, lon, radius_km)

    qs = M.objects.exclude(latitude__isnull=True).exclude(longitude__isnull=True)
    qs = qs.filter(latitude__gte=min_lat, latitude__lte=max_lat, longitude__gte=min_lon, longitude__lte=max_lon)

    if category:
        qs = qs.filter(category__iexact=category.strip())
    if subcategory:
        qs = qs.filter(subcategory__iexact=subcategory.strip())

    qs = qs.filter(_keyword_filter_for_type(t, q))
    qs = qs.annotate(distance_km=RawSQL(HAVERSINE_SQL, (lat, lat, lon))).filter(distance_km__lte=radius_km).order_by("distance_km")

    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size

    fields = _fields_for_type(t)
    items = list(qs.values(*fields, "distance_km")[start:end])

    return {"count": total, "page": page, "page_size": page_size, "items": items}
