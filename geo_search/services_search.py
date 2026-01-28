from typing import Dict, List, Any, Optional
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
            Q(title__icontains=q)
            | Q(employer_name__icontains=q)
            | Q(location_summary__icontains=q)
            | Q(where_youll_work_address__icontains=q)
        )
    return Q()


def _fields_for_type(t: str) -> List[str]:
    if t == "jobs":
        return [
            "id",
            "job_id",
            "title",
            "company",
            "location",
            "job_url",
            "apply_url",
            "image_url",
            "category",
            "subcategory",
            "city",
            "zip_code",
            "state",
            "latitude",
            "longitude",
        ]
    if t == "courses":
        return [
            "id",
            "course_id",
            "course_name",
            "college_name",
            "address",
            "course_url",
            "image_url",
            "category",
            "subcategory",
            "city",
            "zip_code",
            "state",
            "latitude",
            "longitude",
        ]
    if t == "apprenticeships":
        return [
            "id",
            "vacancy_ref",
            "title",
            "employer_name",
            "location_summary",
            "vacancy_url",
            "image_url",
            "category",
            "subcategory",
            "city",
            "zip_code",
            "state",
            "latitude",
            "longitude",
        ]
    return ["id", "latitude", "longitude"]


def _has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _apply_exact_city_postcode_filters(qs, city: Optional[str], postcode: Optional[str]):
    """
    ✅ If user provides city/postcode:
    only match exact DB fields (city/zip_code/etc)
    NOT location_summary or other free text fields.
    """
    city = (city or "").strip()
    postcode = (postcode or "").strip()
    pc_no_space = postcode.replace(" ", "") if postcode else ""

    model = qs.model

    # exact city match
    if city:
        if _has_field(model, "city"):
            qs = qs.filter(city__iexact=city)
        else:
            return qs.none()

    # exact postcode match
    if postcode:
        postcode_fields = ["zip_code", "postcode", "post_code", "postal_code"]
        q_obj = Q()

        for f in postcode_fields:
            if _has_field(model, f):
                q_obj |= Q(**{f"{f}__iexact": postcode})
                if pc_no_space:
                    q_obj |= Q(**{f"{f}__iexact": pc_no_space})

        if q_obj:
            qs = qs.filter(q_obj)
        else:
            return qs.none()

    return qs


def _overwrite_public_id_fields(items: List[Dict[str, Any]], t: str) -> List[Dict[str, Any]]:
    """
    ✅ Force job_id/course_id/vacancy_ref = DB id in response.
    Works even when those fields exist on the model (no annotate conflict).
    """
    for it in items:
        db_id = it.get("id")
        if db_id is None:
            continue

        if t == "jobs":
            it["job_id"] = db_id
        elif t == "courses":
            it["course_id"] = db_id
        elif t == "apprenticeships":
            it["vacancy_ref"] = db_id

    return items


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
    city: Optional[str] = None,
    postcode: Optional[str] = None,
) -> Dict[str, Any]:
    M = _model_for_type(t)

    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), 100)

    min_lat, max_lat, min_lon, max_lon = bbox_for_radius_km(lat, lon, radius_km)

    qs = M.objects.exclude(latitude__isnull=True).exclude(longitude__isnull=True)
    qs = qs.filter(
        latitude__gte=min_lat,
        latitude__lte=max_lat,
        longitude__gte=min_lon,
        longitude__lte=max_lon,
    )

    # ✅ exact city/postcode only (when provided)
    qs = _apply_exact_city_postcode_filters(qs, city=city, postcode=postcode)

    if category:
        qs = qs.filter(category__iexact=category.strip())
    if subcategory:
        qs = qs.filter(subcategory__iexact=subcategory.strip())

    qs = qs.filter(_keyword_filter_for_type(t, q))

    qs = (
        qs.annotate(distance_km=RawSQL(HAVERSINE_SQL, (lat, lat, lon)))
        .filter(distance_km__lte=radius_km)
        .order_by("distance_km")
    )

    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size

    fields = _fields_for_type(t)
    items = list(qs.values(*fields, "distance_km")[start:end])

    # ✅ overwrite job_id/course_id/vacancy_ref with DB id
    items = _overwrite_public_id_fields(items, t)

    return {"count": total, "page": page, "page_size": page_size, "items": items}
