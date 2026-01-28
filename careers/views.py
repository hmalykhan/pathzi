import re
import math

from django.db.models import Subquery, TextField, Value
from django.db.models.functions import Cast, Coalesce, Lower, Replace, Trim
from django.db.models.expressions import RawSQL
from django.utils import timezone
from django.utils.functional import cached_property

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from accounts.models import UserProfile
from careers.models import Career, UserSavedCareer
from careers.api.permissions import CareerPermission
from careers.api.serializers import CareerListSerializer, CareerDetailSerializer

from courses.models import Course
from courses.api.serializer import CoursesSerializer

from jobs.models import Job
from jobs.api.serializers import JobsSerializer

from apprenticeship.models import Apprenticeship
from apprenticeship.api.serializers import ApprenticeshipSerializer


FREE_CAREER_LIMIT = 5
SEPARATORS = [" ", "\n", "\t", "\r", ",", ".", "-", "/", "#"]
GEO_FALLBACK_RADIUS_KM = 40.0


class CareersView(viewsets.ModelViewSet):
    serializer_class = CareerDetailSerializer
    permission_classes = [CareerPermission]
    pagination_class = None

    # -----------------------
    # Cached helpers
    # -----------------------
    @cached_property
    def _profile_cached(self):
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return None
        return UserProfile.objects.filter(appuser=user).first()

    def _get_or_create_profile(self):
        profile, _ = UserProfile.objects.get_or_create(
            appuser=self.request.user,
            defaults={"age": 0},
        )
        return profile

    def _is_subscribed(self) -> bool:
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return False
        billing = getattr(user, "billing", None)
        return bool(billing and billing.is_active)

    # -----------------------
    # Normalization helpers (exact-but-normalized)
    # -----------------------
    def _norm_key(self, s: str) -> str:
        s = (s or "").strip().lower()
        return re.sub(r"[ _-]+", "", s)

    def _normalized_key_expr(self, field_name: str):
        """
        DB side normalization: lower + trim + remove spaces/_/-
        This is NOT fuzzy search. It's exact match on normalized key.
        """
        empty = Value("", output_field=TextField())
        expr = Coalesce(Cast(field_name, output_field=TextField()), empty, output_field=TextField())
        expr = Lower(Trim(expr))
        expr = Replace(expr, Value(" ", output_field=TextField()), empty, output_field=TextField())
        expr = Replace(expr, Value("_", output_field=TextField()), empty, output_field=TextField())
        expr = Replace(expr, Value("-", output_field=TextField()), empty, output_field=TextField())
        return Cast(expr, output_field=TextField())

    def _norm_category_keys(self, profile):
        raw = getattr(profile, "category", None) or []
        if isinstance(raw, str):
            raw = [raw]
        out, seen = [], set()
        for c in raw:
            k = self._norm_key(c)
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(k)
        return out

    def _slice(self, qs):
        qp = getattr(self.request, "query_params", {})
        try:
            limit = int(qp.get("limit") or 0)
            offset = int(qp.get("offset") or 0)
        except (TypeError, ValueError):
            limit, offset = 0, 0

        if limit <= 0:
            return qs

        limit = min(limit, 100)
        offset = max(offset, 0)
        return qs[offset: offset + limit]

    # -----------------------
    # ✅ REPORT MAP helper
    # -----------------------
    def _build_report_map(self, career_ids):
        profile = self._profile_cached
        if not profile or not career_ids:
            return {}
        links = UserSavedCareer.objects.filter(user_profile=profile, career_id__in=career_ids)
        return {l.career_id: l for l in links}

    # -----------------------
    # Careers base queryset
    # -----------------------
    def _filtered_base_queryset(self):
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return Career.objects.none()

        profile = self._profile_cached
        if not profile:
            return Career.objects.none()

        categories = self._norm_category_keys(profile)
        if not categories:
            return Career.objects.none()

        sub_k = self._normalized_key_expr("sub_type")
        return Career.objects.annotate(cat_l=sub_k).filter(cat_l__in=categories)

    def _allowed_ids_subquery(self):
        return self._filtered_base_queryset().order_by("id").values("id")[:FREE_CAREER_LIMIT]

    def get_queryset(self):
        qs = self._filtered_base_queryset().order_by("id")
        if getattr(self, "action", None) == "list" and not self._is_subscribed():
            qs = qs[:FREE_CAREER_LIMIT]
        return qs

    def get_object(self):
        obj = super().get_object()
        if self._is_subscribed():
            return obj

        allowed = Career.objects.filter(id=obj.id, id__in=Subquery(self._allowed_ids_subquery())).exists()
        if not allowed:
            raise NotFound("Not found.")
        return obj

    # -----------------------
    # Geo fallback helpers
    # -----------------------
    def _model_has_field(self, model, field_name: str) -> bool:
        return any(f.name == field_name for f in model._meta.fields)

    def _bbox_for_radius_km(self, lat: float, lon: float, radius_km: float):
        lat = float(lat)
        lon = float(lon)
        radius_km = float(radius_km)

        lat_delta = radius_km / 111.0
        cos_lat = math.cos(math.radians(lat))
        if abs(cos_lat) < 1e-9:
            cos_lat = 1e-9
        lon_delta = radius_km / (111.0 * cos_lat)
        return (lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta)

    def _get_user_active_latlon(self, profile: UserProfile):
        """
        Prefer active Coordinates(active=True). If none, fallback to UserProfile.lat/lng.
        """
        if not profile:
            return (None, None)

        # Coordinates relation exists in your models
        c = profile.coordinates.filter(active=True).order_by("-id").first()
        if c and c.latitude is not None and c.longitude is not None:
            return (float(c.latitude), float(c.longitude))

        if profile.lat is not None and profile.lng is not None:
            return (float(profile.lat), float(profile.lng))

        return (None, None)

    def _geo_radius_filter(self, qs, lat: float, lon: float, radius_km: float):
        """
        Supports both:
        - latitude/longitude
        - lat/lng
        """
        model = qs.model
        if self._model_has_field(model, "latitude") and self._model_has_field(model, "longitude"):
            lat_field, lon_field = "latitude", "longitude"
        elif self._model_has_field(model, "lat") and self._model_has_field(model, "lng"):
            lat_field, lon_field = "lat", "lng"
        else:
            return qs.none()

        min_lat, max_lat, min_lon, max_lon = self._bbox_for_radius_km(lat, lon, radius_km)

        qs = qs.exclude(**{f"{lat_field}__isnull": True}).exclude(**{f"{lon_field}__isnull": True})
        qs = qs.filter(
            **{
                f"{lat_field}__gte": min_lat,
                f"{lat_field}__lte": max_lat,
                f"{lon_field}__gte": min_lon,
                f"{lon_field}__lte": max_lon,
            }
        )

        # Safe: field names come from model introspection, not user input
        hav_sql = f"""
        (6371 * 2 * ASIN(SQRT(
            POWER(SIN(RADIANS({lat_field} - %s) / 2), 2) +
            COS(RADIANS(%s)) * COS(RADIANS({lat_field})) *
            POWER(SIN(RADIANS({lon_field} - %s) / 2), 2)
        )))
        """

        qs = qs.annotate(distance_km=RawSQL(hav_sql, (lat, lat, lon)))
        qs = qs.filter(distance_km__lte=radius_km).order_by("distance_km", "id")
        return qs

    def _exact_city_zip_or_geo(self, base_qs, *, profile: UserProfile, radius_km: float = GEO_FALLBACK_RADIUS_KM):
        """
        Rules:
        - If profile.city exists:
            - try city exact; if none -> geo fallback (40km)
        - If city missing:
            - try zip exact; if none -> geo fallback (40km)
        Returns: (qs, match_flag, note)
        """
        city = (getattr(profile, "city", None) or "").strip()
        zip_code = (getattr(profile, "zip_code", None) or "").strip()

        model = base_qs.model
        has_city = self._model_has_field(model, "city")
        has_zip = self._model_has_field(model, "zip_code")

        # base empty?
        if not base_qs.values("id")[:1].exists():
            return base_qs.none(), "none", "base_pool_empty_after_category_and_subcategory"

        # 1) City path
        if city:
            if has_city:
                city_qs = base_qs.filter(city__iexact=city)
                if city_qs.values("id")[:1].exists():
                    return city_qs.order_by("-id"), "city", "matched_city_exact"
            # city exists but no city match -> GEO fallback
            lat, lon = self._get_user_active_latlon(profile)
            if lat is None or lon is None:
                return base_qs.none(), "none", "city_no_match_and_no_active_coordinates_for_geo"
            geo_qs = self._geo_radius_filter(base_qs, lat, lon, radius_km)
            return geo_qs, f"geo_{int(radius_km)}km", "city_no_match_used_geo_fallback"

        # 2) City missing -> Zip path
        if zip_code and has_zip:
            zip_qs = base_qs.filter(zip_code__iexact=zip_code)
            if zip_qs.values("id")[:1].exists():
                return zip_qs.order_by("-id"), "zip", "matched_zip_exact"

        # 3) GEO fallback (zip missing or zip not matched)
        lat, lon = self._get_user_active_latlon(profile)
        if lat is None or lon is None:
            return base_qs.none(), "none", "no_city_or_zip_and_no_active_coordinates_for_geo"

        geo_qs = self._geo_radius_filter(base_qs, lat, lon, radius_km)
        return geo_qs, f"geo_{int(radius_km)}km", "used_geo_fallback"

    # -----------------------
    # report/list/retrieve/my/save/unsave unchanged
    # -----------------------
    @action(detail=True, methods=["GET", "PUT"], url_path="report")
    def report(self, request, pk=None):
        career = self.get_object()
        profile = self._get_or_create_profile()

        link = UserSavedCareer.objects.filter(user_profile=profile, career_id=career.id).first()
        if not link:
            return Response({"detail": "Career is not saved. Save career first."}, status=status.HTTP_400_BAD_REQUEST)

        if request.method == "GET":
            return Response(
                {"report_status": bool(link.report_status), "report": link.report or {}, "generated_at": link.generated_at},
                status=status.HTTP_200_OK,
            )

        if "career_id" in request.data:
            return Response({"detail": "career_id is not allowed in request body."}, status=status.HTTP_400_BAD_REQUEST)
        if "generated_at" in request.data:
            return Response({"detail": "generated_at is not allowed in request body."}, status=status.HTTP_400_BAD_REQUEST)

        report_data = request.data.get("report", None)
        if report_data is None:
            return Response({"detail": "report is required"}, status=status.HTTP_400_BAD_REQUEST)

        link.report = report_data
        link.report_status = True
        link.generated_at = timezone.now()
        link.save(update_fields=["report", "report_status", "generated_at"])

        return Response(
            {"report_status": bool(link.report_status), "report": link.report, "generated_at": link.generated_at},
            status=status.HTTP_200_OK,
        )

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        careers = list(qs)
        report_map = self._build_report_map([c.id for c in careers])
        serializer = CareerListSerializer(careers, many=True, context={"request": request, "report_map": report_map})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def retrieve(self, request, *args, **kwargs):
        career = self.get_object()
        report_map = self._build_report_map([career.id])
        serializer = CareerDetailSerializer(career, context={"request": request, "report_map": report_map})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"])
    def my(self, request):
        profile = self._get_or_create_profile()
        saved_ids = UserSavedCareer.objects.filter(user_profile=profile).values_list("career_id", flat=True)
        qs = self._filtered_base_queryset().filter(id__in=saved_ids).order_by("id")
        if not self._is_subscribed():
            qs = qs.filter(id__in=Subquery(self._allowed_ids_subquery()))
        careers = list(qs)
        report_map = self._build_report_map([c.id for c in careers])
        serializer = CareerListSerializer(careers, many=True, context={"request": request, "report_map": report_map})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST", "GET"])
    def save(self, request, pk=None):
        career = self.get_object()
        profile = self._get_or_create_profile()
        link, _ = UserSavedCareer.objects.get_or_create(user_profile=profile, career_id=career.id)
        serializer = CareerDetailSerializer(career, context={"request": request, "report_map": {career.id: link}})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST", "GET"])
    def unsave(self, request, pk=None):
        career = self.get_object()
        profile = self._get_or_create_profile()
        deleted, _ = UserSavedCareer.objects.filter(user_profile=profile, career_id=career.id).delete()
        if deleted:
            return Response({"message": "Career unsaved."}, status=status.HTTP_200_OK)
        return Response({"error": "Career was not saved."}, status=status.HTTP_404_NOT_FOUND)

    # -----------------------
    # ✅ Updated: jobs/courses/apprenticeships (no fuzzy, exact normalized)
    # -----------------------
    def _base_pool(self, Model, *, profile: UserProfile, jobname: str):
        """
        Base pool = EXACT subcategory match (normalized) + EXACT category match (normalized).
        """
        cat_keys = self._norm_category_keys(profile)
        if not cat_keys:
            return Model.objects.none()

        job_key = self._norm_key(jobname)
        sub_expr = self._normalized_key_expr("subcategory")
        cat_expr = self._normalized_key_expr("category")

        return (
            Model.objects
            .annotate(sub_k=sub_expr, cat_k=cat_expr)
            .filter(sub_k=job_key, cat_k__in=cat_keys)
        )

    @action(detail=True, methods=["GET"])
    def apprenticeships(self, request, pk=None):
        career = self.get_object()
        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

        profile = self._profile_cached
        if not profile:
            return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

        base_qs = self._base_pool(Apprenticeship, profile=profile, jobname=jobname)

        filtered_qs, match_flag, note = self._exact_city_zip_or_geo(
            base_qs, profile=profile, radius_km=GEO_FALLBACK_RADIUS_KM
        )

        sliced = self._slice(filtered_qs)
        data = ApprenticeshipSerializer(list(sliced), many=True, context={"request": request}).data

        resp = Response(data, status=status.HTTP_200_OK)
        resp["X-Location-Match"] = match_flag if match_flag != "geo_40km" else "geo_40km"
        resp["X-Location-Note"] = note
        return resp

    @action(detail=True, methods=["GET"])
    def jobs(self, request, pk=None):
        career = self.get_object()
        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

        profile = self._profile_cached
        if not profile:
            return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

        base_qs = self._base_pool(Job, profile=profile, jobname=jobname)

        filtered_qs, match_flag, note = self._exact_city_zip_or_geo(
            base_qs, profile=profile, radius_km=GEO_FALLBACK_RADIUS_KM
        )

        sliced = self._slice(filtered_qs)
        data = JobsSerializer(list(sliced), many=True, context={"request": request}).data

        resp = Response(data, status=status.HTTP_200_OK)
        resp["X-Location-Match"] = match_flag if match_flag != "geo_40km" else "geo_40km"
        resp["X-Location-Note"] = note
        return resp

    @action(detail=True, methods=["GET"])
    def courses(self, request, pk=None):
        career = self.get_object()
        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

        profile = self._profile_cached
        if not profile:
            return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

        base_qs = self._base_pool(Course, profile=profile, jobname=jobname)

        filtered_qs, match_flag, note = self._exact_city_zip_or_geo(
            base_qs, profile=profile, radius_km=GEO_FALLBACK_RADIUS_KM
        )

        sliced = self._slice(filtered_qs)
        data = CoursesSerializer(list(sliced), many=True, context={"request": request}).data

        resp = Response(data, status=status.HTTP_200_OK)
        resp["X-Location-Match"] = match_flag if match_flag != "geo_40km" else "geo_40km"
        resp["X-Location-Note"] = note
        return resp

    def get_serializer_class(self):
        if self.action in ("list", "my"):
            return CareerListSerializer
        return CareerDetailSerializer
