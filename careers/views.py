# # careers/views.py
# import operator
# import re
# from functools import reduce

# from django.contrib.postgres.search import TrigramSimilarity
# from django.db.models import (
#     Q,
#     Case,
#     IntegerField,
#     Subquery,
#     TextField,
#     Value,
#     When,
# )
# from django.db.models.functions import Cast, Coalesce, Greatest, Lower, Replace, Trim
# from django.utils.functional import cached_property
# from rest_framework import status, viewsets
# from rest_framework.decorators import action
# from rest_framework.exceptions import PermissionDenied
# from rest_framework.response import Response

# from accounts.models import UserProfile
# from apprenticeship.api.serializers import ApprenticeshipSerializer
# from apprenticeship.models import Apprenticeship
# from careers.api.permissions import CareerPermission
# from careers.api.serializers import CareerDetailSerializer, CareerListSerializer
# from careers.models import Career, UserSavedCareer
# from courses.api.serializer import CoursesSerializer
# from courses.models import Course
# from jobs.api.serializers import JobsSerializer
# from jobs.models import Job

# FREE_CAREER_LIMIT = 5

# SEPARATORS = [" ", "\n", "\t", "\r", ",", ".", "-", "/", "#"]


# class CareersView(viewsets.ModelViewSet):
#     serializer_class = CareerDetailSerializer
#     permission_classes = [CareerPermission]

#     # -----------------------
#     # Cached helpers (1 DB hit for profile per request)
#     # -----------------------
#     @cached_property
#     def _profile_cached(self):
#         user = getattr(self.request, "user", None)
#         if not user or not user.is_authenticated:
#             return None
#         return UserProfile.objects.filter(appuser=user).first()

#     def _get_or_create_profile(self):
#         # for save/unsave/my where you want it guaranteed
#         profile, _ = UserProfile.objects.get_or_create(
#             appuser=self.request.user,
#             defaults={"age": 0},
#         )
#         return profile

#     def _is_subscribed(self) -> bool:
#         user = getattr(self.request, "user", None)
#         if not user or not user.is_authenticated:
#             return False
#         billing = getattr(user, "billing", None)
#         return bool(billing and billing.is_active)

#     def _norm_categories(self, profile):
#         categories = (getattr(profile, "category", None) or [])
#         if isinstance(categories, str):
#             categories = [categories]
#         categories = [c.strip().lower() for c in categories if c and c.strip()]
#         return categories

#     def _normalized_text_expr(self, field_name: str):
#         """
#         Normalize a model text field into 'loc_n' style:
#         lower(trim(coalesce(field, ''))) then remove separators.
#         """
#         empty_text = Value("", output_field=TextField())
#         expr = Coalesce(Cast(field_name, output_field=TextField()), empty_text, output_field=TextField())
#         expr = Lower(Trim(expr))
#         for ch in SEPARATORS:
#             expr = Replace(expr, Value(ch, output_field=TextField()), empty_text, output_field=TextField())
#         return Cast(expr, output_field=TextField())

#     # -----------------------
#     # Careers queryset + free gating
#     # -----------------------
#     def _filtered_base_queryset(self):
#         user = getattr(self.request, "user", None)
#         if not user or not user.is_authenticated:
#             return Career.objects.none()

#         profile = self._profile_cached
#         if not profile:
#             return Career.objects.none()

#         categories = self._norm_categories(profile)
#         if not categories:
#             return Career.objects.none()

#         return Career.objects.annotate(cat_l=Lower("sub_type")).filter(cat_l__in=categories)

#     def _apply_free_limit_if_needed(self, qs):
#         if self._is_subscribed():
#             return qs
#         return qs.order_by("id")[:FREE_CAREER_LIMIT]

#     def get_queryset(self):
#         qs = self._filtered_base_queryset()
#         if getattr(self, "action", None) in ("list", "my"):
#             qs = self._apply_free_limit_if_needed(qs)
#         return qs

#     def get_object(self):
#         obj = super().get_object()

#         if self._is_subscribed():
#             return obj

#         # Subquery: "top 5 allowed ids" without pulling into Python
#         allowed_ids_subq = self._filtered_base_queryset().order_by("id").values("id")[:FREE_CAREER_LIMIT]

#         allowed = Career.objects.filter(id=obj.id, id__in=Subquery(allowed_ids_subq)).exists()
#         if not allowed:
#             raise PermissionDenied("Active subscription required to access this career.")

#         return obj

#     # -----------------------
#     # Actions: save/unsave/my
#     # -----------------------
#     @action(detail=True, methods=["GET", "POST"])
#     def save(self, request, pk=None):
#         career = self.get_object()

#         if request.method.lower() == "get":
#             return Response(self.get_serializer(career).data)

#         profile = self._get_or_create_profile()
#         UserSavedCareer.objects.get_or_create(user_profile=profile, career_id=career.id)
#         return Response(self.get_serializer(career).data, status=status.HTTP_200_OK)

#     @action(detail=True, methods=["GET", "POST"])
#     def unsave(self, request, pk=None):
#         career = self.get_object()

#         if request.method.lower() == "get":
#             return Response(self.get_serializer(career).data)

#         profile = self._get_or_create_profile()
#         deleted, _ = UserSavedCareer.objects.filter(user_profile=profile, career_id=career.id).delete()

#         if deleted:
#             return Response({"message": "Career unsaved."}, status=status.HTTP_200_OK)

#         return Response({"error": "Career was not saved."}, status=status.HTTP_404_NOT_FOUND)

#     @action(detail=False, methods=["GET"])
#     def my(self, request):
#         profile = self._get_or_create_profile()
#         saved_ids = UserSavedCareer.objects.filter(user_profile=profile).values_list("career_id", flat=True)
#         careers = self.get_queryset().filter(id__in=saved_ids)
#         return Response(self.get_serializer(careers, many=True).data, status=status.HTTP_200_OK)

#     # -----------------------
#     # Tailored COURSES (efficient: no exists() + serialize second query)
#     # -----------------------
#     @action(detail=True, methods=["GET"])
#     def courses(self, request, pk=None):
#         career = self.get_object()
#         jobname = (career.jobname or "").strip()
#         if not jobname:
#             return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

#         profile = self._profile_cached
#         if not profile:
#             return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

#         categories = self._norm_categories(profile)
#         if not categories:
#             return Response({"detail": "No categories found for user."}, status=status.HTTP_404_NOT_FOUND)

#         # Base tailored
#         qs = Course.objects.filter(subcategory__iexact=jobname)
#         qs = qs.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

#         # Build words from country/city/zip
#         country = (getattr(profile, "country", None) or "").strip().lower()
#         city = (getattr(profile, "city", None) or "").strip().lower()
#         postal = (getattr(profile, "zip_code", None) or "").strip().lower()
#         profile_text = " ".join([x for x in [country, city, postal] if x])

#         words = [w for w in re.split(r"[^a-z0-9]+", profile_text) if w]
#         words = list(dict.fromkeys(words))
#         if not words:
#             return Response({"detail": "No location data found for user."}, status=status.HTTP_404_NOT_FOUND)

#         threshold = 2 if len(words) >= 2 else 1

#         addr_expr = self._normalized_text_expr("address")
#         qs = qs.annotate(loc_n=addr_expr).exclude(loc_n="")

#         match_expr = Value(0, output_field=IntegerField())
#         for w in words:
#             match_expr += Case(
#                 When(loc_n__contains=w, then=Value(1)),
#                 default=Value(0),
#                 output_field=IntegerField(),
#             )

#         qs = qs.annotate(match_count=match_expr).filter(match_count__gte=threshold).order_by("-match_count")

#         results = list(qs)  # single DB hit
#         if not results:
#             return Response({"detail": "No tailored courses found."}, status=status.HTTP_404_NOT_FOUND)

#         return Response(
#             CoursesSerializer(results, many=True, context={"request": request}).data,
#             status=status.HTTP_200_OK,
#         )

#     # -----------------------
#     # Tailored JOBS (strict -> fuzzy) without extra queries
#     # -----------------------
#     @action(detail=True, methods=["GET"])
#     def jobs(self, request, pk=None):
#         career = self.get_object()
#         jobname = (career.jobname or "").strip()
#         if not jobname:
#             return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

#         profile = self._profile_cached
#         if not profile:
#             return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

#         categories = self._norm_categories(profile)
#         if not categories:
#             return Response({"detail": "No categories found for user."}, status=status.HTTP_404_NOT_FOUND)

#         base_qs = Job.objects.filter(subcategory__iexact=jobname)
#         base_qs = base_qs.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)
#         base_qs = base_qs.exclude(location__isnull=True).exclude(location="")

#         raw_terms = []
#         if profile.city:
#             raw_terms.append(profile.city.strip())
#         if profile.zip_code:
#             raw_terms.append(profile.zip_code.strip())
#         if profile.address:
#             raw_terms.append(profile.address.strip())
#         raw_terms = list({t for t in raw_terms if t})

#         if not raw_terms:
#             return Response({"detail": "No location data found for user."}, status=status.HTTP_404_NOT_FOUND)

#         # 1) strict
#         contains_q = Q()
#         for t in raw_terms:
#             contains_q |= Q(location__icontains=t)

#         strict_qs = base_qs.filter(contains_q)
#         strict_results = list(strict_qs)
#         if strict_results:
#             return Response(
#                 JobsSerializer(strict_results, many=True, context={"request": request}).data,
#                 status=status.HTTP_200_OK,
#             )

#         # 2) fuzzy trigram fallback
#         terms = []
#         for text in raw_terms:
#             for tok in text.replace(",", " ").split():
#                 tok = tok.strip()
#                 if len(tok) >= 3:
#                     terms.append(tok)
#         terms = list(dict.fromkeys(terms))

#         if not terms:
#             return Response({"detail": "No usable location tokens found."}, status=status.HTTP_404_NOT_FOUND)

#         trigram_q = reduce(operator.or_, [Q(location__trigram_similar=t) for t in terms], Q())
#         qs = base_qs.filter(trigram_q)

#         similarities = [TrigramSimilarity("location", t) for t in terms]
#         sim_expr = similarities[0] if len(similarities) == 1 else Greatest(*similarities)

#         qs = qs.annotate(sim=sim_expr).filter(sim__gte=0.3).order_by("-sim")

#         results = list(qs)
#         if not results:
#             return Response({"detail": "No tailored jobs found."}, status=status.HTTP_404_NOT_FOUND)

#         return Response(
#             JobsSerializer(results, many=True, context={"request": request}).data,
#             status=status.HTTP_200_OK,
#         )

#     # -----------------------
#     # Tailored APPRENTICESHIPS (strict merged3 -> match_count -> fuzzy)
#     # -----------------------
#     @action(detail=True, methods=["GET"])
#     def apprenticeships(self, request, pk=None):
#         career = self.get_object()
#         jobname = (career.jobname or "").strip()
#         if not jobname:
#             return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

#         profile = self._profile_cached
#         if not profile:
#             return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

#         categories = self._norm_categories(profile)
#         if not categories:
#             return Response({"detail": "No categories found for user."}, status=status.HTTP_404_NOT_FOUND)

#         base_qs = Apprenticeship.objects.filter(subcategory__iexact=jobname)
#         base_qs = base_qs.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

#         raw_terms = []
#         if getattr(profile, "city", None):
#             raw_terms.append(profile.city.strip().lower())
#         if getattr(profile, "zip_code", None):
#             raw_terms.append(profile.zip_code.strip().lower())
#         if getattr(profile, "address", None):
#             raw_terms.append(profile.address.strip().lower())
#         raw_terms = list({t for t in raw_terms if t})

#         if not raw_terms:
#             return Response({"detail": "No location data found for user."}, status=status.HTTP_404_NOT_FOUND)

#         profile_text = " ".join(raw_terms)
#         words = [w for w in re.split(r"[^a-z0-9]+", profile_text) if w]
#         words = list(dict.fromkeys(words))
#         if not words:
#             return Response({"detail": "No usable location tokens found."}, status=status.HTTP_404_NOT_FOUND)

#         loc_expr = self._normalized_text_expr("location_summary")
#         qs = base_qs.annotate(loc_n=loc_expr).exclude(loc_n="")

#         # 1) strict merged3
#         if len(words) >= 3:
#             merged3 = []
#             for i in range(len(words) - 2):
#                 merged3.append(words[i] + words[i + 1] + words[i + 2])
#             merged3 = list(dict.fromkeys(merged3))

#             strict_q = Q()
#             for m in merged3:
#                 strict_q |= Q(loc_n__contains=m)

#             strict_results = list(qs.filter(strict_q))
#             if strict_results:
#                 return Response(
#                     ApprenticeshipSerializer(strict_results, many=True, context={"request": request}).data,
#                     status=status.HTTP_200_OK,
#                 )

#         # 2) match_count fallback
#         threshold = 2 if len(words) >= 2 else 1

#         match_expr = Value(0, output_field=IntegerField())
#         for w in words:
#             match_expr += Case(
#                 When(loc_n__contains=w, then=Value(1)),
#                 default=Value(0),
#                 output_field=IntegerField(),
#             )

#         word_match_qs = qs.annotate(match_count=match_expr).filter(match_count__gte=threshold).order_by("-match_count")
#         word_match_results = list(word_match_qs)
#         if word_match_results:
#             return Response(
#                 ApprenticeshipSerializer(word_match_results, many=True, context={"request": request}).data,
#                 status=status.HTTP_200_OK,
#             )

#         # 3) fuzzy trigram fallback
#         terms = [w for w in words if len(w) >= 3]
#         terms = list(dict.fromkeys(terms))
#         if not terms:
#             return Response({"detail": "No usable fuzzy tokens found."}, status=status.HTTP_404_NOT_FOUND)

#         similarities = [TrigramSimilarity("loc_n", t) for t in terms]
#         sim_expr = similarities[0] if len(similarities) == 1 else Greatest(*similarities)

#         qs3 = qs.annotate(sim=sim_expr).filter(sim__gte=0.3).order_by("-sim")

#         results = list(qs3)
#         if not results:
#             return Response({"detail": "No tailored apprenticeships found."}, status=status.HTTP_404_NOT_FOUND)

#         return Response(
#             ApprenticeshipSerializer(results, many=True, context={"request": request}).data,
#             status=status.HTTP_200_OK,
#         )

#     # -----------------------
#     # Serializer switching
#     # -----------------------
#     def get_serializer_class(self):
#         if self.action in ("list", "my"):
#             return CareerListSerializer
#         return CareerDetailSerializer


    # @action(detail=True, methods=["GET"])
    # def courses(self, request, pk=None):
    #     career = self.get_object()

    #     jobname = (career.jobname or "").strip()
    #     if not jobname:
    #         return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     tailored_courses = Course.objects.filter(subcategory__iexact=jobname)
    #     if not tailored_courses.exists():
    #         return Response({"detail": "No tailored courses found."}, status=status.HTTP_404_NOT_FOUND)

    #     serializer = CoursesSerializer(tailored_courses, many=True, context={"request": request})
    #     return Response(serializer.data, status=status.HTTP_200_OK)

    # @action(detail=True, methods=["GET"])
    # def jobs(self, request, pk=None):
    #     career = self.get_object()

    #     jobname = (career.jobname or "").strip()
    #     if not jobname:
    #         return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     tailored_jobs = Job.objects.filter(subcategory__iexact=jobname)
    #     if not tailored_jobs.exists():
    #         return Response({"detail": "No tailored jobs found."}, status=status.HTTP_404_NOT_FOUND)

    #     serializer = JobsSerializer(tailored_jobs, many=True, context={"request": request})
    #     return Response(serializer.data, status=status.HTTP_200_OK)

    # @action(detail=True, methods=["GET"])
    # def apprenticeships(self, request, pk=None):
    #     career = self.get_object()

    #     jobname = (career.jobname or "").strip()
    #     if not jobname:
    #         return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     tailored_apps = Apprenticeship.objects.filter(subcategory__iexact=jobname)
    #     if not tailored_apps.exists():
    #         return Response({"detail": "No tailored apprenticeshps found."}, status=status.HTTP_404_NOT_FOUND)

    #     serializer = ApprenticeshipSerializer(tailored_apps, many=True, context={"request": request})
    #     return Response(serializer.data, status=status.HTTP_200_OK)


# careers/views.py
import re

from django.db.models import (
    Case,
    IntegerField,
    Q,
    Subquery,
    TextField,
    Value,
    When,
)
from django.db.models.functions import Cast, Coalesce, Lower, Replace, Trim
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


class CareersView(viewsets.ModelViewSet):
    serializer_class = CareerDetailSerializer
    permission_classes = [CareerPermission]

    # IMPORTANT: disable pagination wrapper for this view even if global pagination is enabled
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

    def _norm_categories(self, profile):
        categories = getattr(profile, "category", None) or []
        if isinstance(categories, str):
            categories = [categories]
        return [c.strip().lower() for c in categories if c and c.strip()]

    def _normalized_text_expr(self, field_name: str):
        empty_text = Value("", output_field=TextField())
        expr = Coalesce(Cast(field_name, output_field=TextField()), empty_text, output_field=TextField())
        expr = Lower(Trim(expr))
        for ch in SEPARATORS:
            expr = Replace(expr, Value(ch, output_field=TextField()), empty_text, output_field=TextField())
        return Cast(expr, output_field=TextField())

    def _slice(self, qs):
        """
        Optional progressive loading WITHOUT changing response shape.
        Frontend can later call: ?limit=20&offset=0, then offset=20, etc.
        """
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
        return qs[offset : offset + limit]

    def _nonempty(self, qs) -> bool:
        return qs.values("id")[:1].exists()

    # -----------------------
    # Careers base queryset + strict hiding of premium careers
    # -----------------------
    def _filtered_base_queryset(self):
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return Career.objects.none()

        profile = self._profile_cached
        if not profile:
            return Career.objects.none()

        categories = self._norm_categories(profile)
        if not categories:
            return Career.objects.none()

        return Career.objects.annotate(cat_l=Lower("sub_type")).filter(cat_l__in=categories)

    def _allowed_ids_subquery(self):
        return (
            self._filtered_base_queryset()
            .order_by("id")
            .values("id")[:FREE_CAREER_LIMIT]
        )

    def get_queryset(self):
        qs = self._filtered_base_queryset().order_by("id")

        # list must show only 5 for free users
        if getattr(self, "action", None) == "list" and not self._is_subscribed():
            qs = qs[:FREE_CAREER_LIMIT]

        return qs

    def get_object(self):
        """
        Free users must NOT access careers outside top 5.
        Return 404 to hide existence.
        """
        obj = super().get_object()

        if self._is_subscribed():
            return obj

        allowed = Career.objects.filter(id=obj.id, id__in=Subquery(self._allowed_ids_subquery())).exists()
        if not allowed:
            raise NotFound("Not found.")
        return obj

    # -----------------------
    # Actions: save / unsave / my
    # -----------------------
    @action(detail=False, methods=["GET"])
    def my(self, request):
        profile = self._get_or_create_profile()

        saved_ids = UserSavedCareer.objects.filter(
            user_profile=profile
        ).values_list("career_id", flat=True)

        qs = self._filtered_base_queryset().filter(id__in=saved_ids).order_by("id")

        # for free users, still restrict to allowed top-5 careers
        if not self._is_subscribed():
            qs = qs.filter(id__in=Subquery(self._allowed_ids_subquery()))

        serializer = CareerListSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST"])
    def save(self, request, pk=None):
        career = self.get_object()
        profile = self._get_or_create_profile()
        UserSavedCareer.objects.get_or_create(user_profile=profile, career_id=career.id)
        serializer = CareerDetailSerializer(career, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST"])
    def unsave(self, request, pk=None):
        career = self.get_object()
        profile = self._get_or_create_profile()
        deleted, _ = UserSavedCareer.objects.filter(user_profile=profile, career_id=career.id).delete()
        if deleted:
            return Response({"message": "Career unsaved."}, status=status.HTTP_200_OK)
        return Response({"error": "Career was not saved."}, status=status.HTTP_404_NOT_FOUND)

    # -----------------------
    # COURSES: strict -> loose -> fallback (still returns list)
    # -----------------------
    @action(detail=True, methods=["GET"])
    def courses(self, request, pk=None):
        career = self.get_object()
        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

        profile = self._profile_cached
        if not profile:
            return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

        categories = self._norm_categories(profile)
        if not categories:
            return Response([], status=status.HTTP_200_OK)

        base_qs = Course.objects.filter(subcategory__iexact=jobname)
        base_qs = base_qs.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

        # country/city/zip words
        country = (getattr(profile, "country", None) or "").strip().lower()
        city = (getattr(profile, "city", None) or "").strip().lower()
        postal = (getattr(profile, "zip_code", None) or "").strip().lower()
        profile_text = " ".join([x for x in [country, city, postal] if x])
        words = [w for w in re.split(r"[^a-z0-9]+", profile_text) if w]
        words = list(dict.fromkeys(words))

        if not self._nonempty(base_qs):
            return Response([], status=status.HTTP_200_OK)

        # If no location data: return tailored+category
        if not words:
            qs = self._slice(base_qs.order_by("id"))
            data = CoursesSerializer(qs, many=True, context={"request": request}).data
            resp = Response(data, status=status.HTTP_200_OK)
            resp["X-Search-Mode"] = "fallback"
            return resp

        addr_expr = self._normalized_text_expr("address")
        qs = base_qs.annotate(loc_n=addr_expr)

        match_expr = Value(0, output_field=IntegerField())
        for w in words:
            match_expr += Case(
                When(loc_n__contains=w, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        qs = qs.annotate(match_count=match_expr)

        strict_threshold = 2 if len(words) >= 2 else 1

        strict_qs = qs.exclude(loc_n="").filter(match_count__gte=strict_threshold).order_by("-match_count", "id")
        loose_qs = qs.exclude(loc_n="").filter(match_count__gte=1).order_by("-match_count", "id")
        fallback_qs = qs.order_by("-match_count", "id")

        if self._nonempty(strict_qs):
            out = self._slice(strict_qs)
            mode = "strict"
        elif self._nonempty(loose_qs):
            out = self._slice(loose_qs)
            mode = "loose"
        else:
            out = self._slice(fallback_qs)
            mode = "fallback"

        data = CoursesSerializer(out, many=True, context={"request": request}).data
        resp = Response(data, status=status.HTTP_200_OK)
        resp["X-Search-Mode"] = mode
        return resp

    # -----------------------
    # JOBS: strict -> loose tokens -> fallback (no trigram lookups; safe on SQLite)
    # -----------------------
    # careers/views.py
import re

from django.db.models import (
    Case,
    IntegerField,
    Q,
    Subquery,
    TextField,
    Value,
    When,
)
from django.db.models.functions import Cast, Coalesce, Lower, Replace, Trim
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


class CareersView(viewsets.ModelViewSet):
    serializer_class = CareerDetailSerializer
    permission_classes = [CareerPermission]

    # IMPORTANT: disable pagination wrapper for this view even if global pagination is enabled
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

    def _norm_categories(self, profile):
        categories = getattr(profile, "category", None) or []
        if isinstance(categories, str):
            categories = [categories]
        return [c.strip().lower() for c in categories if c and c.strip()]

    def _normalized_text_expr(self, field_name: str):
        empty_text = Value("", output_field=TextField())
        expr = Coalesce(Cast(field_name, output_field=TextField()), empty_text, output_field=TextField())
        expr = Lower(Trim(expr))
        for ch in SEPARATORS:
            expr = Replace(expr, Value(ch, output_field=TextField()), empty_text, output_field=TextField())
        return Cast(expr, output_field=TextField())

    def _slice(self, qs):
        """
        Optional progressive loading WITHOUT changing response shape.
        Frontend can later call: ?limit=20&offset=0, then offset=20, etc.
        """
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
        return qs[offset : offset + limit]

    def _nonempty(self, qs) -> bool:
        return qs.values("id")[:1].exists()

    # -----------------------
    # Careers base queryset + strict hiding of premium careers
    # -----------------------
    def _filtered_base_queryset(self):
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return Career.objects.none()

        profile = self._profile_cached
        if not profile:
            return Career.objects.none()

        categories = self._norm_categories(profile)
        if not categories:
            return Career.objects.none()

        return Career.objects.annotate(cat_l=Lower("sub_type")).filter(cat_l__in=categories)

    def _allowed_ids_subquery(self):
        return (
            self._filtered_base_queryset()
            .order_by("id")
            .values("id")[:FREE_CAREER_LIMIT]
        )

    def get_queryset(self):
        qs = self._filtered_base_queryset().order_by("id")

        # list must show only 5 for free users
        if getattr(self, "action", None) == "list" and not self._is_subscribed():
            qs = qs[:FREE_CAREER_LIMIT]

        return qs

    def get_object(self):
        """
        Free users must NOT access careers outside top 5.
        Return 404 to hide existence.
        """
        obj = super().get_object()

        if self._is_subscribed():
            return obj

        allowed = Career.objects.filter(id=obj.id, id__in=Subquery(self._allowed_ids_subquery())).exists()
        if not allowed:
            raise NotFound("Not found.")
        return obj

    # -----------------------
    # Actions: save / unsave / my
    # -----------------------
    @action(detail=False, methods=["GET"])
    def my(self, request):
        profile = self._get_or_create_profile()

        saved_ids = UserSavedCareer.objects.filter(
            user_profile=profile
        ).values_list("career_id", flat=True)

        qs = self._filtered_base_queryset().filter(id__in=saved_ids).order_by("id")

        # for free users, still restrict to allowed top-5 careers
        if not self._is_subscribed():
            qs = qs.filter(id__in=Subquery(self._allowed_ids_subquery()))

        serializer = CareerListSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST"])
    def save(self, request, pk=None):
        career = self.get_object()
        profile = self._get_or_create_profile()
        UserSavedCareer.objects.get_or_create(user_profile=profile, career_id=career.id)
        serializer = CareerDetailSerializer(career, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST"])
    def unsave(self, request, pk=None):
        career = self.get_object()
        profile = self._get_or_create_profile()
        deleted, _ = UserSavedCareer.objects.filter(user_profile=profile, career_id=career.id).delete()
        if deleted:
            return Response({"message": "Career unsaved."}, status=status.HTTP_200_OK)
        return Response({"error": "Career was not saved."}, status=status.HTTP_404_NOT_FOUND)
    

    def _location_terms(self, profile):
        # take ALL location-related profile fields
        country = (getattr(profile, "country", None) or "").strip().lower()
        city = (getattr(profile, "city", None) or "").strip().lower()
        postal = (getattr(profile, "zip_code", None) or "").strip().lower()
        address = (getattr(profile, "address", None) or "").strip().lower()

        raw_terms = [t for t in [city, postal, address] if t]  # exact considers these strongly
        raw_terms = list(dict.fromkeys(raw_terms))  # dedupe keep order

        # tokens used for fuzzy “makes sense”
        profile_text = " ".join([x for x in [country, city, postal, address] if x])
        words = [w for w in re.split(r"[^a-z0-9]+", profile_text) if w]
        words = list(dict.fromkeys(words))

        return raw_terms, words


    def _merge_exact_then_fuzzy(
        self,
        *,
        base_qs,
        field_name: str,
        serializer_cls,
        request,
        default_limit: int = 50,
    ):
        """
        1) exact: full-term icontains match (city/zip/address) + rank by exact_score
        2) fuzzy: token match_count on normalized field + rank by match_count
        Append fuzzy results if exact results are not enough.
        Returns plain list JSON (no pagination wrapper).
        """

        profile = self._profile_cached
        if not profile:
            return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

        raw_terms, words = self._location_terms(profile)

        # Optional progressive loading without changing shape
        qp = getattr(request, "query_params", {})
        try:
            limit = int(qp.get("limit") or 0)
            offset = int(qp.get("offset") or 0)
        except (TypeError, ValueError):
            limit, offset = 0, 0

        limit = min(limit, 100) if limit > 0 else 0
        offset = max(offset, 0)

        desired = (offset + limit) if limit > 0 else default_limit

        # If no location data at all: just return tailored base
        if not raw_terms and not words:
            items = list(base_qs.order_by("-id")[:desired])
            items = items[offset : offset + limit] if limit > 0 else items
            return Response(serializer_cls(items, many=True, context={"request": request}).data, status=status.HTTP_200_OK)

        # ---------- EXACT stage (city/zip/address full strings) ----------
        exact_q = Q()
        for t in raw_terms:
            exact_q |= Q(**{f"{field_name}__icontains": t})

        exact_score = Value(0, output_field=IntegerField())
        for t in raw_terms:
            exact_score += Case(
                When(**{f"{field_name}__icontains": t}, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )

        exact_qs = base_qs
        if raw_terms:
            exact_qs = base_qs.filter(exact_q).annotate(exact_score=exact_score).order_by("-exact_score", "id")
        else:
            exact_qs = base_qs.none()

        exact_list = list(exact_qs[:desired])
        exact_ids = [obj.id for obj in exact_list]

        # ---------- FUZZY stage (token match_count on normalized field) ----------
        # use normalized loc_n for robust matching
        loc_expr = self._normalized_text_expr(field_name)
        fuzzy_qs = base_qs.annotate(loc_n=loc_expr).exclude(loc_n="")

        # token match_count
        match_expr = Value(0, output_field=IntegerField())
        for w in words:
            match_expr += Case(
                When(loc_n__contains=w, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )

        fuzzy_qs = (
            fuzzy_qs.annotate(match_count=match_expr)
            .filter(match_count__gte=1)
            .order_by("-match_count", "id")
        )

        if exact_ids:
            fuzzy_qs = fuzzy_qs.exclude(id__in=exact_ids)

        need = max(0, desired - len(exact_list))
        fuzzy_list = list(fuzzy_qs[:need]) if need > 0 else []

        # If NO exact results, return fuzzy (still makes sense)
        if not exact_list:
            combined = fuzzy_list
            mode = "fuzzy_only"
        else:
            # exact exists → enrich by appending fuzzy
            combined = exact_list + fuzzy_list
            mode = "exact_plus_fuzzy"

        # If still empty (rare), fallback to tailored base
        if not combined:
            combined = list(base_qs.order_by("-id")[:desired])
            mode = "fallback"

        # Apply offset/limit AFTER merging
        combined = combined[offset : offset + limit] if limit > 0 else combined

        data = serializer_cls(combined, many=True, context={"request": request}).data
        resp = Response(data, status=status.HTTP_200_OK)
        resp["X-Search-Mode"] = mode
        return resp

    @action(detail=True, methods=["GET"])
    def jobs(self, request, pk=None):
        ENRICH_MIN = 10

        career = self.get_object()
        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

        profile = self._profile_cached
        if not profile:
            return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

        categories = self._norm_categories(profile)
        if not categories:
            return Response([], status=status.HTTP_200_OK)

        # Base: tailored + category
        base_qs = Job.objects.filter(subcategory__iexact=jobname)
        base_qs = base_qs.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

        if not base_qs.values("id")[:1].exists():
            return Response([], status=status.HTTP_200_OK)

        # limit/offset without changing response shape
        try:
            limit = int(request.query_params.get("limit") or 0)
            offset = int(request.query_params.get("offset") or 0)
        except (TypeError, ValueError):
            limit, offset = 0, 0

        limit = min(limit, 100) if limit > 0 else 0
        offset = max(offset, 0)
        desired = (offset + limit) if limit > 0 else 50
        desired = max(desired, ENRICH_MIN)

        # Profile location signals
        city = (getattr(profile, "city", None) or "").strip().lower()
        postal = (getattr(profile, "zip_code", None) or "").strip().lower()
        addr = (getattr(profile, "address", None) or "").strip().lower()
        country = (getattr(profile, "country", None) or "").strip().lower()

        raw_terms = [t for t in [city, postal, addr] if t]
        raw_terms = list(dict.fromkeys(raw_terms))

        profile_text = " ".join([x for x in [country, city, postal, addr] if x])
        words = [w for w in re.split(r"[^a-z0-9]+", profile_text) if w]
        words = list(dict.fromkeys(words))[:12]  # cap for SQL size

        empty_text = Value("", output_field=TextField())

        def _qs_with_text(qs):
            loc_text = Coalesce(Cast("location", output_field=TextField()), empty_text, output_field=TextField())
            return qs.annotate(loc_text=loc_text).exclude(loc_text="")

        def _add_loc_n(qs):
            loc_n = Lower(Trim(qs.query.annotations["loc_text"]))
            for ch in [" ", "\n", "\t", "\r", ",", ".", "-", "/", "#"]:
                loc_n = Replace(loc_n, Value(ch, output_field=TextField()), empty_text, output_field=TextField())
            loc_n = Cast(loc_n, output_field=TextField())
            return qs.annotate(loc_n=loc_n).exclude(loc_n="")

        # ---------- EXACT ----------
        exact_list = []
        qs1 = _qs_with_text(base_qs)

        if raw_terms:
            exact_score = Value(0, output_field=IntegerField())
            for t in raw_terms:
                exact_score += Case(
                    When(loc_text__icontains=t, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )

            exact_required = 2 if len(raw_terms) >= 2 else 1
            exact_qs = (
                qs1.annotate(exact_score=exact_score)
                .filter(exact_score__gte=exact_required)
                .order_by("-exact_score", "id")
            )
            exact_list = list(exact_qs[:desired])

        # If exact is already strong enough -> return only exact
        if len(exact_list) >= ENRICH_MIN:
            combined = exact_list
            mode = "exact_only"
        else:
            combined = list(exact_list)
            ids = {o.id for o in combined}

            # ---------- FUZZY (base) ----------
            if words:
                qs2 = _add_loc_n(qs1)

                match_expr = Value(0, output_field=IntegerField())
                for w in words:
                    match_expr += Case(
                        When(loc_n__contains=w, then=Value(1)),
                        default=Value(0),
                        output_field=IntegerField(),
                    )

                fuzzy_base = (
                    qs2.annotate(match_count=match_expr)
                    .filter(match_count__gte=1)
                    .exclude(id__in=ids)
                    .order_by("-match_count", "id")
                )

                need = max(0, desired - len(combined))
                combined += list(fuzzy_base[:need])
                ids = {o.id for o in combined}

            # ---------- BROADEN (same subcategory, ignore category) ----------
            if len(combined) < desired and words:
                broad_qs = Job.objects.filter(subcategory__iexact=jobname)
                broad_qs = _qs_with_text(broad_qs)
                broad_qs = _add_loc_n(broad_qs)

                match_expr = Value(0, output_field=IntegerField())
                for w in words:
                    match_expr += Case(
                        When(loc_n__contains=w, then=Value(1)),
                        default=Value(0),
                        output_field=IntegerField(),
                    )

                fuzzy_broad = (
                    broad_qs.annotate(match_count=match_expr)
                    .filter(match_count__gte=1)
                    .exclude(id__in=ids)
                    .order_by("-match_count", "id")
                )

                need = max(0, desired - len(combined))
                combined += list(fuzzy_broad[:need])
                ids = {o.id for o in combined}

            # ---------- LAST fallback fill (if DB has more but they don’t match location tokens) ----------
            if len(combined) < desired:
                need = desired - len(combined)
                combined += list(qs1.exclude(id__in=ids).order_by("-id")[:need])

            if not combined:
                combined = list(base_qs.order_by("-id")[:desired])
                mode = "fallback"
            else:
                mode = "exact_plus_fuzzy" if exact_list else "fuzzy_only"

        # Slice AFTER combine
        combined = combined[offset: offset + limit] if limit > 0 else combined

        data = JobsSerializer(combined, many=True, context={"request": request}).data
        resp = Response(data, status=200)
        resp["X-Search-Mode"] = mode
        return resp


    
    @action(detail=True, methods=["GET"])
    def apprenticeships(self, request, pk=None):
        ENRICH_MIN = 10

        career = self.get_object()
        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

        profile = self._profile_cached
        if not profile:
            return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

        categories = self._norm_categories(profile)
        if not categories:
            return Response([], status=status.HTTP_200_OK)

        base_qs = Apprenticeship.objects.filter(subcategory__iexact=jobname)
        base_qs = base_qs.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

        if not base_qs.values("id")[:1].exists():
            return Response([], status=status.HTTP_200_OK)

        try:
            limit = int(request.query_params.get("limit") or 0)
            offset = int(request.query_params.get("offset") or 0)
        except (TypeError, ValueError):
            limit, offset = 0, 0

        limit = min(limit, 100) if limit > 0 else 0
        offset = max(offset, 0)
        desired = (offset + limit) if limit > 0 else 50
        desired = max(desired, ENRICH_MIN)

        city = (getattr(profile, "city", None) or "").strip().lower()
        postal = (getattr(profile, "zip_code", None) or "").strip().lower()
        addr = (getattr(profile, "address", None) or "").strip().lower()
        country = (getattr(profile, "country", None) or "").strip().lower()

        raw_terms = [t for t in [city, postal, addr] if t]
        raw_terms = list(dict.fromkeys(raw_terms))

        profile_text = " ".join([x for x in [country, city, postal, addr] if x])
        words = [w for w in re.split(r"[^a-z0-9]+", profile_text) if w]
        words = list(dict.fromkeys(words))[:12]

        empty_text = Value("", output_field=TextField())

        def _qs_with_text(qs):
            loc_text = Coalesce(Cast("location_summary", output_field=TextField()), empty_text, output_field=TextField())
            return qs.annotate(loc_text=loc_text).exclude(loc_text="")

        def _add_loc_n(qs):
            loc_n = Lower(Trim(qs.query.annotations["loc_text"]))
            for ch in [" ", "\n", "\t", "\r", ",", ".", "-", "/", "#"]:
                loc_n = Replace(loc_n, Value(ch, output_field=TextField()), empty_text, output_field=TextField())
            loc_n = Cast(loc_n, output_field=TextField())
            return qs.annotate(loc_n=loc_n).exclude(loc_n="")

        # ---------- EXACT ----------
        exact_list = []
        qs1 = _qs_with_text(base_qs)

        if raw_terms:
            exact_score = Value(0, output_field=IntegerField())
            for t in raw_terms:
                exact_score += Case(
                    When(loc_text__icontains=t, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )

            exact_required = 2 if len(raw_terms) >= 2 else 1
            exact_qs = (
                qs1.annotate(exact_score=exact_score)
                .filter(exact_score__gte=exact_required)
                .order_by("-exact_score", "id")
            )
            exact_list = list(exact_qs[:desired])

        if len(exact_list) >= ENRICH_MIN:
            combined = exact_list
            mode = "exact_only"
        else:
            combined = list(exact_list)
            ids = {o.id for o in combined}

            # ---------- FUZZY (base) ----------
            if words:
                qs2 = _add_loc_n(qs1)

                match_expr = Value(0, output_field=IntegerField())
                for w in words:
                    match_expr += Case(
                        When(loc_n__contains=w, then=Value(1)),
                        default=Value(0),
                        output_field=IntegerField(),
                    )

                fuzzy_base = (
                    qs2.annotate(match_count=match_expr)
                    .filter(match_count__gte=1)
                    .exclude(id__in=ids)
                    .order_by("-match_count", "id")
                )

                need = max(0, desired - len(combined))
                combined += list(fuzzy_base[:need])
                ids = {o.id for o in combined}

            # ---------- BROADEN ----------
            if len(combined) < desired and words:
                broad_qs = Apprenticeship.objects.filter(subcategory__iexact=jobname)
                broad_qs = _qs_with_text(broad_qs)
                broad_qs = _add_loc_n(broad_qs)

                match_expr = Value(0, output_field=IntegerField())
                for w in words:
                    match_expr += Case(
                        When(loc_n__contains=w, then=Value(1)),
                        default=Value(0),
                        output_field=IntegerField(),
                    )

                fuzzy_broad = (
                    broad_qs.annotate(match_count=match_expr)
                    .filter(match_count__gte=1)
                    .exclude(id__in=ids)
                    .order_by("-match_count", "id")
                )

                need = max(0, desired - len(combined))
                combined += list(fuzzy_broad[:need])
                ids = {o.id for o in combined}

            # ---------- LAST fallback fill ----------
            if len(combined) < desired:
                need = desired - len(combined)
                combined += list(qs1.exclude(id__in=ids).order_by("-id")[:need])

            if not combined:
                combined = list(base_qs.order_by("-id")[:desired])
                mode = "fallback"
            else:
                mode = "exact_plus_fuzzy" if exact_list else "fuzzy_only"

        combined = combined[offset: offset + limit] if limit > 0 else combined

        data = ApprenticeshipSerializer(combined, many=True, context={"request": request}).data
        resp = Response(data, status=200)
        resp["X-Search-Mode"] = mode
        return resp


    
    @action(detail=True, methods=["GET"])
    def courses(self, request, pk=None):
        ENRICH_MIN = 10
        WORD_CAP = 12  # keep SQL light

        career = self.get_object()
        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

        profile = self._profile_cached
        if not profile:
            return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

        categories = self._norm_categories(profile)
        if not categories:
            return Response([], status=status.HTTP_200_OK)

        # 0) Strict pool: subcategory + category
        base_qs = Course.objects.filter(subcategory__iexact=jobname)
        base_qs = base_qs.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

        if not base_qs.values("id")[:1].exists():
            # still try broaden (subcategory only) before returning empty
            broaden_check = Course.objects.filter(subcategory__iexact=jobname)
            if not broaden_check.values("id")[:1].exists():
                return Response([], status=status.HTTP_200_OK)
            base_qs = broaden_check  # fallback to broaden pool if strict pool empty

        # limit/offset without changing response shape
        try:
            limit = int(request.query_params.get("limit") or 0)
            offset = int(request.query_params.get("offset") or 0)
        except (TypeError, ValueError):
            limit, offset = 0, 0

        limit = min(limit, 100) if limit > 0 else 0
        offset = max(offset, 0)
        desired = (offset + limit) if limit > 0 else 50
        desired = max(desired, ENRICH_MIN)

        # 1) Profile location signals
        city = (getattr(profile, "city", None) or "").strip().lower()
        postal = (getattr(profile, "zip_code", None) or "").strip().lower()
        addr = (getattr(profile, "address", None) or "").strip().lower()
        country = (getattr(profile, "country", None) or "").strip().lower()

        raw_terms = [t for t in [city, postal, addr] if t]
        raw_terms = list(dict.fromkeys(raw_terms))

        profile_text = " ".join([x for x in [country, city, postal, addr] if x])
        words = [w for w in re.split(r"[^a-z0-9]+", profile_text) if w]
        words = list(dict.fromkeys(words))[:WORD_CAP]

        empty_text = Value("", output_field=TextField())

        # Safe text view of Course.address (works for JSON/text/null)
        addr_text = Coalesce(Cast("address", output_field=TextField()), empty_text, output_field=TextField())

        def normalize_expr(expr):
            loc_n = Lower(Trim(expr))
            for ch in [" ", "\n", "\t", "\r", ",", ".", "-", "/", "#"]:
                loc_n = Replace(loc_n, Value(ch, output_field=TextField()), empty_text, output_field=TextField())
            return Cast(loc_n, output_field=TextField())

        # Strict queryset with addr_text
        qs1 = base_qs.annotate(addr_text=addr_text).exclude(addr_text="")

        # ---------- EXACT (score-based) ----------
        exact_list = []
        if raw_terms:
            exact_score = Value(0, output_field=IntegerField())
            for t in raw_terms:
                exact_score += Case(
                    When(addr_text__icontains=t, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )

            exact_required = 2 if len(raw_terms) >= 2 else 1

            exact_qs = (
                qs1.annotate(exact_score=exact_score)
                .filter(exact_score__gte=exact_required)
                .order_by("-exact_score", "id")
            )
            exact_list = list(exact_qs[:desired])

        # If exact strong enough -> return exact only
        if len(exact_list) >= ENRICH_MIN:
            combined = exact_list
            mode = "exact_only"
        else:
            combined = list(exact_list)
            ids = {o.id for o in combined}

            # ---------- FUZZY within strict pool ----------
            if words:
                loc_n = normalize_expr(addr_text)
                match_expr = Value(0, output_field=IntegerField())
                for w in words:
                    match_expr += Case(
                        When(loc_n__contains=w, then=Value(1)),
                        default=Value(0),
                        output_field=IntegerField(),
                    )

                fuzzy_strict = (
                    qs1.annotate(loc_n=loc_n, match_count=match_expr)
                    .filter(match_count__gte=1)
                    .exclude(id__in=ids)
                    .order_by("-match_count", "id")
                )

                need = max(0, desired - len(combined))
                combined += list(fuzzy_strict[:need])
                ids = {o.id for o in combined}

            # ---------- BROADEN: subcategory only (relax category), fuzzy again ----------
            if len(combined) < desired and words:
                broad_base = Course.objects.filter(subcategory__iexact=jobname)
                broad_qs = broad_base.annotate(addr_text=addr_text).exclude(addr_text="")

                loc_n = normalize_expr(addr_text)
                match_expr = Value(0, output_field=IntegerField())
                for w in words:
                    match_expr += Case(
                        When(loc_n__contains=w, then=Value(1)),
                        default=Value(0),
                        output_field=IntegerField(),
                    )

                fuzzy_broad = (
                    broad_qs.annotate(loc_n=loc_n, match_count=match_expr)
                    .filter(match_count__gte=1)
                    .exclude(id__in=ids)
                    .order_by("-match_count", "id")
                )

                need = max(0, desired - len(combined))
                combined += list(fuzzy_broad[:need])
                ids = {o.id for o in combined}

            # ---------- LAST fill: pull remaining tailored items (strict pool), then broaden pool ----------
            if len(combined) < desired:
                need = desired - len(combined)
                combined += list(qs1.exclude(id__in=ids).order_by("-id")[:need])
                ids = {o.id for o in combined}

            if len(combined) < desired:
                need = desired - len(combined)
                broad_fill = Course.objects.filter(subcategory__iexact=jobname).exclude(id__in=ids).order_by("-id")[:need]
                combined += list(broad_fill)

            if not combined:
                # if subcategory has literally 0 rows, only then this happens
                combined = list(Course.objects.filter(subcategory__iexact=jobname).order_by("-id")[:desired])
                mode = "fallback"
            else:
                mode = "exact_plus_fuzzy" if exact_list else "fuzzy_only"

        # Final slice AFTER combining (keeps exact-first ordering)
        combined = combined[offset: offset + limit] if limit > 0 else combined

        data = CoursesSerializer(combined, many=True, context={"request": request}).data
        resp = Response(data, status=200)
        resp["X-Search-Mode"] = mode
        return resp






    # -----------------------
    # COURSES: strict -> loose -> fallback (still returns list)
    # -----------------------
    # @action(detail=True, methods=["GET"])
    # def courses(self, request, pk=None):
    #     career = self.get_object()
    #     jobname = (career.jobname or "").strip()
    #     if not jobname:
    #         return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     profile = self._profile_cached
    #     if not profile:
    #         return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     categories = self._norm_categories(profile)
    #     if not categories:
    #         return Response([], status=status.HTTP_200_OK)

    #     base_qs = Course.objects.filter(subcategory__iexact=jobname)
    #     base_qs = base_qs.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

    #     # country/city/zip words
    #     country = (getattr(profile, "country", None) or "").strip().lower()
    #     city = (getattr(profile, "city", None) or "").strip().lower()
    #     postal = (getattr(profile, "zip_code", None) or "").strip().lower()
    #     profile_text = " ".join([x for x in [country, city, postal] if x])
    #     words = [w for w in re.split(r"[^a-z0-9]+", profile_text) if w]
    #     words = list(dict.fromkeys(words))

    #     if not self._nonempty(base_qs):
    #         return Response([], status=status.HTTP_200_OK)

    #     # If no location data: return tailored+category
    #     if not words:
    #         qs = self._slice(base_qs.order_by("id"))
    #         data = CoursesSerializer(qs, many=True, context={"request": request}).data
    #         resp = Response(data, status=status.HTTP_200_OK)
    #         resp["X-Search-Mode"] = "fallback"
    #         return resp

    #     addr_expr = self._normalized_text_expr("address")
    #     qs = base_qs.annotate(loc_n=addr_expr)

    #     match_expr = Value(0, output_field=IntegerField())
    #     for w in words:
    #         match_expr += Case(
    #             When(loc_n__contains=w, then=Value(1)),
    #             default=Value(0),
    #             output_field=IntegerField(),
    #         )
    #     qs = qs.annotate(match_count=match_expr)

    #     strict_threshold = 2 if len(words) >= 2 else 1

    #     strict_qs = qs.exclude(loc_n="").filter(match_count__gte=strict_threshold).order_by("-match_count", "id")
    #     loose_qs = qs.exclude(loc_n="").filter(match_count__gte=1).order_by("-match_count", "id")
    #     fallback_qs = qs.order_by("-match_count", "id")

    #     if self._nonempty(strict_qs):
    #         out = self._slice(strict_qs)
    #         mode = "strict"
    #     elif self._nonempty(loose_qs):
    #         out = self._slice(loose_qs)
    #         mode = "loose"
    #     else:
    #         out = self._slice(fallback_qs)
    #         mode = "fallback"

    #     data = CoursesSerializer(out, many=True, context={"request": request}).data
    #     resp = Response(data, status=status.HTTP_200_OK)
    #     resp["X-Search-Mode"] = mode
    #     return resp

    # # -----------------------
    # # JOBS: strict -> loose tokens -> fallback (no trigram lookups; safe on SQLite)
    # # -----------------------
    # @action(detail=True, methods=["GET"])
    # def jobs(self, request, pk=None):
    #     career = self.get_object()
    #     jobname = (career.jobname or "").strip()
    #     if not jobname:
    #         return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     profile = self._profile_cached
    #     if not profile:
    #         return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     categories = self._norm_categories(profile)
    #     if not categories:
    #         return Response([], status=status.HTTP_200_OK)

    #     base_qs = Job.objects.filter(subcategory__iexact=jobname)
    #     base_qs = base_qs.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

    #     if not self._nonempty(base_qs):
    #         return Response([], status=status.HTTP_200_OK)

    #     raw_terms = []
    #     if getattr(profile, "city", None):
    #         raw_terms.append(profile.city.strip())
    #     if getattr(profile, "zip_code", None):
    #         raw_terms.append(profile.zip_code.strip())
    #     if getattr(profile, "address", None):
    #         raw_terms.append(profile.address.strip())
    #     raw_terms = list({t for t in raw_terms if t})

    #     # No location data => return tailored jobs
    #     if not raw_terms:
    #         out = self._slice(base_qs.order_by("-id"))
    #         data = JobsSerializer(out, many=True, context={"request": request}).data
    #         resp = Response(data, status=status.HTTP_200_OK)
    #         resp["X-Search-Mode"] = "fallback"
    #         return resp

    #     # strict
    #     strict_q = Q()
    #     for t in raw_terms:
    #         strict_q |= Q(location__icontains=t)
    #     strict_qs = base_qs.exclude(location__isnull=True).exclude(location="").filter(strict_q).order_by("-id")

    #     if self._nonempty(strict_qs):
    #         out = self._slice(strict_qs)
    #         mode = "strict"
    #     else:
    #         # loose token match
    #         tokens = []
    #         for text in raw_terms:
    #             for tok in text.replace(",", " ").split():
    #                 tok = tok.strip()
    #                 if len(tok) >= 3:
    #                     tokens.append(tok)
    #         tokens = list(dict.fromkeys(tokens))

    #         if tokens:
    #             loose_q = Q()
    #             for t in tokens:
    #                 loose_q |= Q(location__icontains=t)
    #             loose_qs = base_qs.exclude(location__isnull=True).exclude(location="").filter(loose_q).order_by("-id")
    #         else:
    #             loose_qs = Job.objects.none()

    #         if self._nonempty(loose_qs):
    #             out = self._slice(loose_qs)
    #             mode = "loose"
    #         else:
    #             out = self._slice(base_qs.order_by("-id"))
    #             mode = "fallback"

    #     data = JobsSerializer(out, many=True, context={"request": request}).data
    #     resp = Response(data, status=status.HTTP_200_OK)
    #     resp["X-Search-Mode"] = mode
    #     return resp

    # # -----------------------
    # # APPRENTICESHIPS: strict merged3 -> match_count -> fallback
    # # -----------------------
    # @action(detail=True, methods=["GET"])
    # def apprenticeships(self, request, pk=None):
    #     career = self.get_object()
    #     jobname = (career.jobname or "").strip()
    #     if not jobname:
    #         return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     profile = self._profile_cached
    #     if not profile:
    #         return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     categories = self._norm_categories(profile)
    #     if not categories:
    #         return Response([], status=status.HTTP_200_OK)

    #     # 0) Tailored base (career + category)
    #     base_qs = Apprenticeship.objects.filter(subcategory__iexact=jobname)
    #     base_qs = base_qs.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

    #     if not self._nonempty(base_qs):
    #         return Response([], status=status.HTTP_200_OK)

    #     # 1) Build words from country/city/zip/address (same as courses)
    #     country = (getattr(profile, "country", None) or "").strip().lower()
    #     city = (getattr(profile, "city", None) or "").strip().lower()
    #     postal = (getattr(profile, "zip_code", None) or "").strip().lower()
    #     addr = (getattr(profile, "address", None) or "").strip().lower()

    #     profile_text = " ".join([x for x in [country, city, postal, addr] if x])
    #     words = [w for w in re.split(r"[^a-z0-9]+", profile_text) if w]
    #     words = list(dict.fromkeys(words))

    #     if not words:
    #         out = self._slice(base_qs.order_by("-id"))
    #         data = ApprenticeshipSerializer(out, many=True, context={"request": request}).data
    #         resp = Response(data, status=status.HTTP_200_OK)
    #         resp["X-Search-Mode"] = "fallback"
    #         return resp

    #     # 2) Normalize location_summary -> loc_n
    #     loc_expr = self._normalized_text_expr("location_summary")
    #     qs = base_qs.annotate(loc_n=loc_expr).exclude(loc_n="")

    #     # 3) match_count
    #     match_expr = Value(0, output_field=IntegerField())
    #     for w in words:
    #         match_expr += Case(
    #             When(loc_n__contains=w, then=Value(1)),
    #             default=Value(0),
    #             output_field=IntegerField(),
    #         )

    #     qs = qs.annotate(match_count=match_expr)

    #     strict_threshold = 2 if len(words) >= 2 else 1

    #     strict_qs = qs.filter(match_count__gte=strict_threshold).order_by("-match_count", "id")
    #     loose_qs = qs.filter(match_count__gte=1).order_by("-match_count", "id")
    #     fallback_qs = qs.order_by("-match_count", "id")

    #     if self._nonempty(strict_qs):
    #         out = self._slice(strict_qs)
    #         mode = "strict"
    #     elif self._nonempty(loose_qs):
    #         out = self._slice(loose_qs)
    #         mode = "loose"
    #     else:
    #         out = self._slice(fallback_qs)
    #         mode = "fallback"

    #     data = ApprenticeshipSerializer(out, many=True, context={"request": request}).data
    #     resp = Response(data, status=status.HTTP_200_OK)
    #     resp["X-Search-Mode"] = mode
    #     return resp


    # -----------------------
    # Serializer switching
    # -----------------------
    def get_serializer_class(self):
        if self.action in ("list", "my"):
            return CareerListSerializer
        return CareerDetailSerializer
