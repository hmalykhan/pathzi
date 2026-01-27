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
    GET /geo/autocomplete/?text=...&types=jobs,courses&limit=8

    Strategy:
    1) If looks like postcode -> try DB postcode suggestions, if empty -> Geoapify
    2) Else -> try DB city suggestions, if empty -> Geoapify
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        text = (request.query_params.get("text") or request.query_params.get("q") or "").strip()
        if len(text) < 2:
            return Response({"status": True, "kind": "unknown", "data": []})

        types = parse_types(request.query_params.get("types"))
        limit = int(request.query_params.get("limit") or 8)
        limit = min(max(limit, 1), 20)

        # Cache key depends on input + types + limit
        cache_key = f"geo_autocomplete:v3:{text.lower()}:{','.join(types)}:{limit}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        # 1) Decide if it's "probably postcode"
        kind_guess = detect_search_kind(text)  # city/postcode/address (guess)
        data = []
        kind_final = ""

        # If postcode guess -> try postcode DB first
        if kind_guess == "postcode":
            data = db_suggest_distinct("zip_code", text, types, limit=limit)
            if data:
                kind_final = "postcode"
            else:
                # fallback to Geoapify (maybe it's address with numbers)
                kind_final = "address"
                country = getattr(settings, "GEOAPIFY_DEFAULT_COUNTRY", "") or ""
                data = geoapify_autocomplete(text, limit=limit, country_code=country)

        else:
            # 2) Try city DB first (for everything that isn't postcode)
            data = db_suggest_distinct("city", text, types, limit=limit)
            if data:
                kind_final = "city"
            else:
                # fallback to Geoapify address
                kind_final = "address"
                # optional: don't call geoapify on very short input
                if len(text) < 3:
                    data = []
                else:
                    country = getattr(settings, "GEOAPIFY_DEFAULT_COUNTRY", "") or ""
                    data = geoapify_autocomplete(text, limit=limit, country_code=country)

        resp = {"status": True, "kind": kind_final, "data": data}
        cache.set(cache_key, resp, timeout=60 * 10)
        return Response(resp)


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

    ✅ If city/postcode provided:
      - filter by exact city/postcode fields only (no location_summary partial matching)
    ✅ Also returns DB primary key as the value for job_id/course_id/vacancy_ref
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

        # Decide center
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

        results = {
            t: search_nearby(
                t=t,
                lat=lat,
                lon=lon,
                radius_km=radius_km,
                q=q,
                category=category,
                subcategory=subcategory,
                page=page,
                page_size=page_size,
                city=city or None,
                postcode=postcode or None,
            )
            for t in types
        }

        return Response(
            {
                "status": True,
                "center_source": center_source,
                "center": {"lat": lat, "lon": lon},
                "radius_km": radius_km,
                "types": types,
                "results": results,
            }
        )
    """
    POST /geo/nearby/
    Uses:
    - location.lat/lon (address) OR
    - location.city OR location.postcode -> resolves DB centroid -> radius search

    ✅ If city/postcode provided:
      - filter by exact city/postcode fields only (no location_summary partial matching)
    ✅ Also returns DB primary key as the value for job_id/course_id/vacancy_ref
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

        # Decide center
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

        results = {
            t: search_nearby(
                t=t,
                lat=lat,
                lon=lon,
                radius_km=radius_km,
                q=q,
                category=category,
                subcategory=subcategory,
                page=page,
                page_size=page_size,
                city=city or None,
                postcode=postcode or None,
            )
            for t in types
        }

        return Response(
            {
                "status": True,
                "center_source": center_source,
                "center": {"lat": lat, "lon": lon},
                "radius_km": radius_km,
                "types": types,
                "results": results,
            }
        )
    """
    POST /geo/nearby/

    Uses:
    - location.lat/lon (address) OR
    - location.city OR location.postcode -> resolves DB centroid -> radius search

    NEW BEHAVIOR:
    - If user provides city -> results must match EXACT city field (case-insensitive)
    - If user provides postcode -> results must match EXACT postcode/zip field (case-insensitive)
    - Each returned record includes DB primary key "id"
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

        # Decide center
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

        # ✅ PASS city/postcode into search_nearby so results match EXACT city/zip fields
        results = {
            t: search_nearby(
                t,
                lat,
                lon,
                radius_km,
                q=q,
                category=category,
                subcategory=subcategory,
                page=page,
                page_size=page_size,
                city=city or None,
                postcode=postcode or None,
            )
            for t in types
        }

        return Response(
            {
                "status": True,
                "center_source": center_source,
                "center": {"lat": lat, "lon": lon},
                "radius_km": radius_km,
                "types": types,
                "filters": {
                    "city": city or None,
                    "postcode": postcode or None,
                    "q": q or None,
                    "category": category or None,
                    "subcategory": subcategory or None,
                },
                "results": results,
            }
        )