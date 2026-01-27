from django.conf import settings
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .utils import detect_search_kind
from .services_geoapify import geoapify_autocomplete
from .services_db import (
    db_suggest_distinct,
    db_list_distinct_with_counts,
    weighted_centroid_for_city_or_postcode,
)
from .services_search import search_nearby

# ✅ tolerate typos/aliases from frontend
TYPE_ALIASES = {
    "job": "jobs",
    "jobs": "jobs",
    "course": "courses",
    "courses": "courses",
    "cource": "courses",
    "cources": "courses",
    "apprenticeship": "apprenticeships",
    "apprenticeships": "apprenticeships",
    "apprentiship": "apprenticeships",
    "apprentiships": "apprenticeships",
}
ALLOWED_TYPES = {"jobs", "courses", "apprenticeships"}

def parse_types(value):
    if not value:
        return ["jobs", "courses", "apprenticeships"]

    if isinstance(value, list):
        raw = value
    else:
        raw = [x.strip() for x in str(value).split(",") if x.strip()]

    normalized = []
    for t in raw:
        t2 = TYPE_ALIASES.get(t.strip().lower())
        if t2 and t2 in ALLOWED_TYPES:
            normalized.append(t2)

    # if user sent garbage -> fallback to all
    return list(dict.fromkeys(normalized)) or ["jobs", "courses", "apprenticeships"]


class LocationAutocompleteAPI(APIView):
    """
    GET /geo/autocomplete/?text=lah&types=jobs,courses&limit=8
    - city/postcode -> DB
    - address -> Geoapify
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        text = (request.query_params.get("text") or request.query_params.get("q") or "").strip()
        if len(text) < 2:
            return Response({"status": True, "kind": "unknown", "data": []})

        types = parse_types(request.query_params.get("types"))
        limit = int(request.query_params.get("limit") or 8)
        limit = min(max(limit, 1), 20)

        kind = detect_search_kind(text)

        # ✅ caching makes repeated calls instant
        cache_key = f"geo_autocomplete:v2:{kind}:{text.lower()}:{','.join(types)}:{limit}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response({"status": True, "kind": kind, "data": cached})

        if kind == "city":
            data = db_suggest_distinct("city", text, types, limit=limit)
        elif kind == "postcode":
            data = db_suggest_distinct("zip_code", text, types, limit=limit)
        else:
            # ✅ avoid hammering geoapify on 1-2 chars
            if len(text) < 3:
                data = []
            else:
                country = getattr(settings, "GEOAPIFY_DEFAULT_COUNTRY", "") or ""
                try:
                    data = geoapify_autocomplete(text, limit=limit, country_code=country)
                except Exception:
                    data = []

        cache.set(cache_key, data, timeout=60 * 10)
        return Response({"status": True, "kind": kind, "data": data})


class CitiesListAPI(APIView):
    """
    GET /geo/cities/?types=jobs,courses&limit=500&q=la
    Returns distinct cities from DB (with counts).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        types = parse_types(request.query_params.get("types"))
        q = request.query_params.get("q") or ""
        limit = int(request.query_params.get("limit") or 500)
        limit = min(max(limit, 1), 5000)

        cache_key = f"geo_cities:v1:{q.lower()}:{','.join(types)}:{limit}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response({"status": True, "data": cached})

        data = db_list_distinct_with_counts("city", types=types, q=q, limit=limit)
        cache.set(cache_key, data, timeout=60 * 30)
        return Response({"status": True, "data": data})


class PostcodesListAPI(APIView):
    """
    GET /geo/postcodes/?types=jobs&limit=500&q=54
    Returns distinct postcodes from DB (with counts).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        types = parse_types(request.query_params.get("types"))
        q = request.query_params.get("q") or ""
        limit = int(request.query_params.get("limit") or 500)
        limit = min(max(limit, 1), 5000)

        cache_key = f"geo_postcodes:v1:{q.lower()}:{','.join(types)}:{limit}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response({"status": True, "data": cached})

        data = db_list_distinct_with_counts("zip_code", types=types, q=q, limit=limit)
        cache.set(cache_key, data, timeout=60 * 30)
        return Response({"status": True, "data": data})


class NearbySearchAPI(APIView):
    """
    POST /geo/nearby/
    Uses:
    - location.lat/lon (address) OR
    - location.city OR location.postcode -> resolves DB centroid -> radius search
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        body = request.data or {}
        types = parse_types(body.get("types"))
        radius_km = float(body.get("radius_km") or 50)
        radius_km = min(max(radius_km, 1.0), 200.0)

        location = body.get("location") or {}
        q = body.get("q") or ""
        category = body.get("category") or ""
        subcategory = body.get("subcategory") or ""
        page = int(body.get("page") or 1)
        page_size = int(body.get("page_size") or 20)

        lat = location.get("lat")
        lon = location.get("lon")
        city = (location.get("city") or "").strip()
        postcode = (location.get("postcode") or location.get("zip_code") or "").strip()

        if lat is not None and lon is not None:
            lat = float(lat)
            lon = float(lon)
            center_source = "address"
        else:
            center = weighted_centroid_for_city_or_postcode(
                city=city or None,
                postcode=postcode or None,
                types=types,
            )
            if not center:
                return Response(
                    {"status": False, "message": "No coordinates found for selected city/postcode in DB."},
                    status=400,
                )
            lat, lon = center
            center_source = "db_centroid"

        results = {t: search_nearby(t, lat, lon, radius_km, q=q, category=category, subcategory=subcategory, page=page, page_size=page_size)
                   for t in types}

        return Response({
            "status": True,
            "center_source": center_source,
            "center": {"lat": lat, "lon": lon},
            "radius_km": radius_km,
            "types": types,
            "results": results,
        })
