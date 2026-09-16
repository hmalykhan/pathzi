# For payment method limited careers for unsubsctibed uncomment 160, 211
import logging
import re, time
from django.core.cache import cache
from pathzi.cache_utils import cache_add, cache_delete, cache_get, cache_set
from django.db.models import Case, When
from django.db.models import Subquery
from django.utils import timezone
from django.utils.functional import cached_property
from django.shortcuts import get_object_or_404

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from accounts.models import UserProfile
from careers.models import Career, UserCareerReport, UserSavedCareer, UserExploredCareer
from careers.api.permissions import CareerPermission
from careers.api.serializers import CareerListSerializer, CareerDetailSerializer, CareerFilterSerializer, _empty_my_report

from courses.models import Course
from courses.api.serializer import CoursesSerializer

from jobs.models import Job
from jobs.api.serializers import JobsSerializer

from apprenticeship.models import Apprenticeship
from apprenticeship.api.serializers import ApprenticeshipSerializer

from accounts.services.career_recommender import update_embedding_and_recs_async
from careers.services.recommendation_triggers import trigger_recs_debounced
from accounts.services.recommendation_cache import get_explored_cache_key, get_saved_cache_key, get_list_cache_key, get_recs_lock_key, get_embedding_schedule_lock_key, get_pathways_cache_key
from careers.services import pathway as pathway_service
from accounts.services.user_service import get_explored_careers, get_saved_careers, get_career_queryset, norm_key
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from careers.api.serializers import BulkCareerInteractionSerializer
from careers.services.interactions_bulk import apply_bulk_career_interactions
from careers.throttles import InteractionThrottle
from rest_framework.permissions import IsAuthenticated

from analytics.services import log_activity
from analytics import constants as analytics_constants
from careers.services.nearby_routes import (
    PostcodeNotFound,
    attach_distances,
    attach_relevance,
    nearest_route_items,
    parse_radius_miles,
    rank_by_relevance,
    requested_origin,
    saved_origin,
    wants_relevance,
)
from careers.services.free_tier import free_tier_careers, paywall_enforced
from billing.services.access import access_for
from careers.services.career_deck import CARD_FIELDS, guest_deck, unique_careers
from careers.services.match_score import match_scores, with_match_scores

logger = logging.getLogger(__name__)

FREE_CAREER_LIMIT = 5

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

    @staticmethod
    def _debounced_embedding_refresh(user_id, *, cooldown=30):
        """
        Coalesce rapid swipe bursts: only trigger a recompute if no other
        rebuild was triggered for this user within `cooldown` seconds.
        cache.add is atomic across Gunicorn workers via Redis.
        """
        if cache_add(f"recs_triggered:{user_id}", True, timeout=cooldown):
            trigger_recs_debounced(user_id)

    # -----------------------
    # Pagination helper (keeps schema same)
    # -----------------------
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
        return qs[offset: offset + limit]

    # -----------------------
    # ✅ REPORT MAP helper (for my_report in serializers)
    # -----------------------
    

    # -----------------------
    # Careers base queryset + strict hiding of premium careers
    # -----------------------

    def normalize_sub_type(value: str) -> str:
        value = value or ""
        value = value.strip().lower()
        value = re.sub(r"[ _-]+", "", value)
        return value


    def _norm_key(self, s: str) -> str:
        # lowercase + trim + remove spaces/_/-
        s = (s or "").strip().lower()
        return re.sub(r"[ _-]+", "", s)

    def _filtered_base_queryset(self):
        """
        NOTE: This is for listing Careers only (unchanged).
        """
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return Career.objects.none()

        profile = self._profile_cached
        if not profile:
            return Career.objects.none()

        raw_categories = getattr(profile, "category", None) or []
        if isinstance(raw_categories, str):
            raw_categories = [raw_categories]

        categories = []
        seen = set()
        for c in raw_categories:
            k = self._norm_key(c)
            if not k or k in seen:
                continue
            seen.add(k)
            categories.append(k)

        if not categories:
            return Career.objects.all().order_by("id")
        return Career.objects.filter(normalized_sub_type__in=categories).order_by("id")

    def _allowed_ids_subquery(self):
        return (
            self._filtered_base_queryset()
            .order_by("id")
            .values("id")[:FREE_CAREER_LIMIT]
        )

    def get_queryset(self):
        # qs = self._filtered_base_queryset().order_by("id")

        qs = self._filtered_base_queryset()
        # list must show only 5 for free users
        # if getattr(self, "action", None) == "list" and not self._is_subscribed():
        #     qs = qs[:FREE_CAREER_LIMIT]

        # For single-career endpoints (retrieve / jobs / courses /
        # apprenticeships / save / unsave / explore / unexplore / report),
        # restrict free users to their top-5 allowed careers AT THE QUERYSET
        # LEVEL. Doing it here means get_object()'s lookup is filtered in
        # the same SQL statement instead of needing a follow-up .exists()
        # check, saving one round-trip per free-user request.

        # New for the subscribed login uncomment when want to subscribed logic
        # detail_actions = {
        #     "retrieve",
        #     "jobs",
        #     "courses",
        #     "apprenticeships",
        #     "save",
        #     "unsave",
        #     "explore",
        #     "unexplore",
        #     "report",
        # }
        # if (
        #     getattr(self, "action", None) in detail_actions
        #     and self.request.user.is_authenticated
        #     and not self.request.user.is_staff
        #     and not self._is_subscribed()
        # ):
        #     qs = qs.filter(id__in=Subquery(self._allowed_ids_subquery()))

        return qs
    
    def _build_saved_map(self, career_ids):
        profile = self._profile_cached
        if not profile:
            return {}

        ids = UserSavedCareer.objects.filter(
            user_profile=profile,
            career_id__in=career_ids
        ).values_list("career_id", flat=True)

        return {cid: True for cid in ids}


    def _build_explored_map(self, career_ids):
        profile = self._profile_cached
        if not profile:
            return {}

        ids = UserExploredCareer.objects.filter(
            user_profile=profile,
            career_id__in=career_ids
        ).values_list("career_id", flat=True)

        return {cid: True for cid in ids}
    
    def _build_report_map(self, career_ids):
        """
        Return {career_id: UserCareerReport} for current user_profile.
        Used to embed my_report per career without N+1 queries.
        """
        profile = self._profile_cached
        if not profile or not career_ids:
            return {}
        links = UserCareerReport.objects.filter(
            user_profile=profile,
            career_id__in=career_ids,
        )
        return {l.career_id: l for l in links}
    
    def get_object(self):
        """
        Free users must NOT access careers outside top 5.
        Return 404 to hide existence.

        The top-5 restriction is now enforced inside get_queryset() for
        detail actions, so super().get_object() will already raise 404 when
        a free user requests a career outside their allowed set — no second
        .exists() round-trip needed.
        """

        # ✅ Admin/staff can retrieve ANY career by ID (bypass filtered queryset)
        if self.request.user.is_authenticated and self.request.user.is_staff:
            lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
            lookup_value = self.kwargs.get(lookup_url_kwarg)

            obj = get_object_or_404(
                Career.objects.all(),
                **{self.lookup_field: lookup_value}
            )
            self.check_object_permissions(self.request, obj)
            return obj

        # ------------------------------------------------------------------
        # OLD: two-query version (kept for reference)
        #
        #   obj = super().get_object()                      # query #1
        #   if self._is_subscribed():
        #       return obj
        #   allowed = Career.objects.filter(                # query #2
        #       id=obj.id,
        #       id__in=Subquery(self._allowed_ids_subquery())
        #   ).exists()
        #   if not allowed:
        #       raise NotFound("Not found.")
        #   return obj
        # ------------------------------------------------------------------
        return super().get_object()

    # @action(detail=True, methods=["GET", "PUT"], url_path="report")
    # def report(self, request, pk=None):
    #     # Match DRF get_object() behavior: invalid pk => 404 {"detail":"Not found."}
    #     try:
    #         career_id = int(pk)
    #     except (TypeError, ValueError):
    #         raise NotFound()

    #     profile = self._get_or_create_profile()

    #     # Cheap exists check (instead of fetching the full Career row)
    #     if not Career.objects.filter(id=career_id).exists():
    #         raise NotFound()

    #     qs = UserSavedCareer.objects.filter(
    #         user_profile=profile,
    #         career__id=career_id
    #     )

    #     if request.method == "GET":
    #         row = qs.values("report_status", "report", "generated_at").first()
    #         if not row:
    #             return Response(
    #                 {"detail": "Career is not saved. Save career first."},
    #                 status=status.HTTP_400_BAD_REQUEST,
    #             )

    #         return Response(
    #             {
    #                 "report_status": bool(row["report_status"]),
    #                 "report": row["report"] or {},
    #                 "generated_at": row["generated_at"],
    #             },
    #             status=status.HTTP_200_OK,
    #         )

    #     if "career_id" in request.data:
    #         return Response(
    #             {"detail": "career_id is not allowed in request body."},
    #             status=status.HTTP_400_BAD_REQUEST,
    #         )
    #     if "generated_at" in request.data:
    #         return Response(
    #             {"detail": "generated_at is not allowed in request body."},
    #             status=status.HTTP_400_BAD_REQUEST,
    #         )

    #     report_data = request.data.get("report", None)
    #     if report_data is None:
    #         return Response(
    #             {"detail": "report is required"},
    #             status=status.HTTP_400_BAD_REQUEST,
    #         )

    #     now = timezone.now()

    #     updated = qs.update(
    #         report=report_data,
    #         report_status=True,
    #         generated_at=now,
    #     )

    #     if updated == 0:
    #         return Response(
    #             {"detail": "Career is not saved. Save career first."},
    #             status=status.HTTP_400_BAD_REQUEST,
    #         )
    #     cache.delete(get_saved_cache_key(request.user.id))
    #     return Response(
    #         {
    #             "report_status": True,
    #             "report": report_data,
    #             "generated_at": now,
    #         },
    #         status=status.HTTP_200_OK,
    #     )

    # -----------------------
    # list/retrieve unchanged
    # -----------------------

    # original
    # def list(self, request, *args, **kwargs):
    #     qs = self.get_queryset()
    #     careers = list(qs)

    #     report_map = self._build_report_map([c.id for c in careers])

    #     serializer = CareerListSerializer(
    #         careers,
    #         many=True,
    #         context={"request": request, "report_map": report_map},
    #     )
    #     return Response(serializer.data, status=status.HTTP_200_OK)


    # def list(self, request, *args, **kwargs):
    #     user = request.user
    #     if not user or not user.is_authenticated:
    #         return Response([], status=status.HTTP_200_OK)

    #     profile = self._profile_cached
    #     if not profile:
    #         return Response([], status=status.HTTP_200_OK)
    #     qss = get_career_queryset(user, profile)
    #     print("this is the length of the qss",len(qss))
    #     # print("this is the profile name : ",profile.name)
        
    #     # categories = list(profile.category)

    #     # saved_ids = UserSavedCareer.objects.filter(
    #     #     user_profile=profile
    #     # ).values_list("career_id", flat=True)

    #     # saved_careers = list(
    #     #     Career.objects.filter(id__in=saved_ids).distinct()
    #     # )

    #     # saved_careers = list(self._filtered_base_queryset().filter(id__in=saved_ids).order_by("id"))

    #     # explored_careers = list(
    #     #     Career.objects.filter(
    #     #         explored_user_links__user_profile=profile
    #     #     ).distinct()
    #     # )

    #     # explored_ids = UserExploredCareer.objects.filter(
    #     #     user_profile=profile
    #     # ).values_list("career_id", flat=True)

    #     # explored_careers = list(self._filtered_base_queryset().filter(id__in=explored_ids).order_by("id"))

        


    #     # print("these are the saved careers of this user : ",sv)
    #     # print("thesea are the explored careers of this user : ", ex)
    #     # bool = True
    #     # for category in categories:
    #     #     print(f"this is the categories : {category} \n ")
    #     #     if bool == True:
    #     #         print("inside\n")

    #     cache_key = get_list_cache_key(user.id)
    #     cached_ids = cache.get(cache_key)
    #     if cached_ids is None:
    #         print("CACHE MISS ❌")
    #         rec_result = recommend_careers_for_user(
    #                     user=user,
    #                     queryset=qss,
    #                     # saved_careers=saved_careers,
    #                     # explored_careers=explored_careers,
    #                     top_k=50,
    #                 )
    #         if rec_result["recommendations"] == None:
    #             print("fallback is running from the list function.")
    #             ex=get_explored_careers(profile)
    #             sv=get_saved_careers(profile)
    #             schedule_embedding_update(request.user, ex=ex, sv=sv)
    #             careers = qss
    #             precompute_recommendations_async(request.user, qss)
    #                 # bool = False
    #             # elif bool == False:
    #             #     print("outside\n")
    #             #     rec_result["recommendations"] += recommend_careers_for_user(
    #             #             user=user,
    #             #             category=category,
    #             #             saved_careers=saved_careers,
    #             #             explored_careers=explored_careers,
    #             #             top_k=30,
    #             #         )["recommendations"]

    #         else:   
    #             print(f"this is the len of all recomendations : {len(rec_result["recommendations"])}")

    #             recommended_ids = [item["career_id"] for item in rec_result["recommendations"]]
    #             cache.set(cache_key, recommended_ids, timeout=60 * 60)

    #             # careers_qs = Career.objects.filter(id__in=recommended_ids)
    #             # careers_by_id = {career.id: career for career in careers_qs}
    #             # careers_by_id = {
    #             #     c.id:c for c in qss if c.id in recommended_ids
    #             # }

    #             # careers = [
    #             #     careers_by_id[cid]
    #             #     for cid in recommended_ids
    #             #     if cid in careers_by_id
    #             # ]

    #             # career_ids = [c.id for c in careers]
    #             # report_map = self._build_report_map(career_ids)
    #             # saved_map = self._build_saved_map(career_ids)
    #             # explored_map = self._build_explored_map(career_ids)
    #             careers = Career.objects.filter(id__in=recommended_ids)

    #     else:
    #         print("CACHE HIT ✅")
    #         recommended_ids = cached_ids
    #         careers = Career.objects.filter(id__in=recommended_ids)

    #     serializer = CareerListSerializer(
    #         careers,
    #         many=True,
    #         # context={
    #         #     "request": request,
    #         #     # "report_map": {},
    #         #     # "saved_map": {},
    #         #     # "explored_map": {},
    #         # },
    #     )
    #     return Response(serializer.data, status=status.HTTP_200_OK)


    # @action(detail=True, methods=["GET", "PUT"], url_path="report")
    # def report(self, request, pk=None):

    #     try:
    #         career_id = int(pk)
    #     except (TypeError, ValueError):
    #         raise NotFound()

    #     profile = self._get_or_create_profile()

    #     # 🔥 single DB fetch
    #     career = get_object_or_404(Career, id=career_id)

    #     qs = UserSavedCareer.objects.filter(
    #         user_profile=profile,
    #         career_id=career.id
    #     )

    #     if request.method == "GET":
    #         row = qs.values("report_status", "report", "generated_at").first()

    #         if not row:
    #             return Response(
    #                 {"detail": "Career is not saved. Save career first."},
    #                 status=status.HTTP_400_BAD_REQUEST,
    #             )

    #         return Response(
    #             {
    #                 "report_status": bool(row["report_status"]),
    #                 "report": row["report"] or {},
    #                 "generated_at": row["generated_at"],
    #             },
    #             status=status.HTTP_200_OK,
    #         )

    #     # 🔥 validation
    #     if "career_id" in request.data:
    #         return Response(
    #             {"detail": "career_id is not allowed"},
    #             status=status.HTTP_400_BAD_REQUEST,
    #         )

    #     if "generated_at" in request.data:
    #         return Response(
    #             {"detail": "generated_at is not allowed"},
    #             status=status.HTTP_400_BAD_REQUEST,
    #         )

    #     if "report" not in request.data:
    #         return Response(
    #             {"detail": "report is required"},
    #             status=status.HTTP_400_BAD_REQUEST,
    #         )

    #     report_data = request.data["report"]
    #     now = timezone.now()

    #     updated = qs.update(
    #         report=report_data,
    #         report_status=True,
    #         generated_at=now,
    #     )

    #     if updated == 0:
    #         return Response(
    #             {"detail": "Career is not saved. Save career first."},
    #             status=status.HTTP_400_BAD_REQUEST,
    #         )

    #     # 🔥 cache invalidation (important)
    #     cache.delete(get_saved_cache_key(request.user.id))
    #     cache.delete(get_list_cache_key(request.user.id))

    #     return Response(
    #         {
    #             "report_status": True,
    #             "report": report_data,
    #             "generated_at": now,
    #         },
    #         status=status.HTTP_200_OK,
    #     )


# @action(detail=True, methods=["GET", "POST", "PUT"], url_path="report")
# def report(self, request, pk=None):

#     try:
#         career_id = int(pk)
#     except (TypeError, ValueError):
#         raise NotFound()

#     profile = self._get_or_create_profile()

#     # 🔥 GET → only fetch (fast, no extra work)
#     if request.method == "GET":
#         row = UserSavedCareer.objects.filter(
#             user_profile=profile,
#             career_id=career_id
#         ).values("report_status", "report", "generated_at").first()

#         if not row:
#             return Response(
#                 {"detail": "Career is not saved."},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         return Response(
#             {
#                 "report_status": bool(row["report_status"]),
#                 "report": row["report"] or {},
#                 "generated_at": row["generated_at"],
#             },
#             status=status.HTTP_200_OK,
#         )

#     # 🔥 WRITE (POST / PUT)

#     # validation
#     if "career_id" in request.data:
#         return Response(
#             {"detail": "career_id is not allowed"},
#             status=status.HTTP_400_BAD_REQUEST,
#         )

#     if "generated_at" in request.data:
#         return Response(
#             {"detail": "generated_at is not allowed"},
#             status=status.HTTP_400_BAD_REQUEST,
#         )

#     if "report" not in request.data:
#         return Response(
#             {"detail": "report is required"},
#             status=status.HTTP_400_BAD_REQUEST,
#         )

#     report_data = request.data["report"]
#     now = timezone.now()

#     # 🔥 UPSERT (save career if not exists + update report)
#     obj, _ = UserSavedCareer.objects.get_or_create(
#         user_profile=profile,
#         career_id=career_id,
#         defaults={
#             "report": report_data,
#             "report_status": True,
#             "generated_at": now,
#         }
#     )

#     # 🔥 If already exists → update
#     if obj.report != report_data or not obj.report_status:
#         UserSavedCareer.objects.filter(id=obj.id).update(
#             report=report_data,
#             report_status=True,
#             generated_at=now,
#         )

#     # 🔥 cache invalidation (important)
#     cache.delete(get_saved_cache_key(request.user.id))
#     cache.delete(get_list_cache_key(request.user.id))

#     # 🔥 async (non-blocking)
#     update_embedding_and_recs_async(request.user.id)

#     return Response(
#         {
#             "report_status": True,
#             "report": report_data,
#             "generated_at": now,
#         },
#         status=status.HTTP_200_OK,
#     )

    @action(detail=True, methods=["GET", "POST", "PUT", "DELETE"], url_path="report")
    def report(self, request, pk=None):
        """
        The user's report for this career ("saved pathway"), stored on its own:
        saving a report doesn't save the career, and unsaving the career keeps it.
          GET         -> { report_status, report, generated_at }  (empty when there is none)
          POST / PUT  -> create or replace   body: { "report": {...}, "report_status": bool (optional) }
          DELETE      -> remove it
        """
        try:
            career_id = int(pk)
        except (TypeError, ValueError):
            raise NotFound()

        profile = self._profile_cached or self._get_or_create_profile()
        reports = UserCareerReport.objects.filter(user_profile=profile, career_id=career_id)

        if request.method == "GET":
            row = reports.values("report_status", "report", "generated_at").first()
            if not row:
                return Response(_empty_my_report(), status=status.HTTP_200_OK)
            return Response(
                {
                    "report_status": bool(row["report_status"]),
                    "report": row["report"] or {},
                    "generated_at": row["generated_at"],
                },
                status=status.HTTP_200_OK,
            )

        if request.method == "DELETE":
            deleted, _ = reports.delete()
            if not deleted:
                return Response(
                    {"status": False, "message": "No report for this career."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            cache_delete(get_saved_cache_key(request.user.id))  # /careers/my/ embeds my_report
            return Response({"status": True, "deleted": True}, status=status.HTTP_200_OK)

        if "career_id" in request.data:
            return Response(
                {"detail": "career_id is not allowed in request body."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if "generated_at" in request.data:
            return Response(
                {"detail": "generated_at is not allowed in request body."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if "report" not in request.data:
            return Response(
                {"detail": "report is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        get_object_or_404(Career, pk=career_id)

        report_data = request.data["report"]
        report_status = bool(request.data.get("report_status", True))
        now = timezone.now()

        UserCareerReport.objects.update_or_create(
            user_profile=profile,
            career_id=career_id,
            defaults={"report": report_data, "report_status": report_status, "generated_at": now},
        )
        cache_delete(get_saved_cache_key(request.user.id))  # /careers/my/ embeds my_report

        return Response(
            {
                "report_status": report_status,
                "report": report_data,
                "generated_at": now,
            },
            status=status.HTTP_200_OK,
        )

    # -----------------------
    # AI career pathway (#24). Generation moved off the phone: see
    # AI_PATHWAY_GENERATION.md and careers/services/pathway.py.
    # -----------------------
    @action(detail=True, methods=["GET"], url_path="pathway")
    def pathway(self, request, pk=None):
        """
        GET /careers/{id}/pathway/

        Returns the user's pathway for this career, generating it only when
        there isn't a usable one already. Every generated pathway is stored
        straight away with user_saved=False, so opening the same career
        again is free; it appears in "my saved pathways" only once the user
        presses Save.

        Regenerated when the profile fields that change the answer change -
        education level above all - or when the prompt version moves on.
        """
        try:
            career_id = int(pk)
        except (TypeError, ValueError):
            raise NotFound()

        profile = self._profile_cached or self._get_or_create_profile()
        career = get_object_or_404(Career, pk=career_id)

        fingerprint = pathway_service.profile_fingerprint(profile)
        row = UserCareerReport.objects.filter(user_profile=profile, career_id=career_id).first()

        fresh = (
            row is not None
            and bool(row.report)
            and row.profile_fingerprint == fingerprint
            and row.prompt_version == pathway_service.PROMPT_VERSION
        )
        regenerate = (request.query_params.get("refresh") or "").lower() in ("1", "true", "yes")

        if fresh and not regenerate:
            return Response(self._pathway_payload(career, row, generated=False),
                            status=status.HTTP_200_OK)

        try:
            report = pathway_service.generate(profile, career)
        except pathway_service.PathwayUnavailable as e:
            # An existing pathway, even a stale one, beats an error screen.
            if row is not None and row.report:
                payload = self._pathway_payload(career, row, generated=False)
                payload["stale"] = True
                return Response(payload, status=status.HTTP_200_OK)
            return Response(
                {"status": False, "message": str(e), "code": "pathway_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        now = timezone.now()
        row, _ = UserCareerReport.objects.update_or_create(
            user_profile=profile,
            career_id=career_id,
            defaults={
                "report": report,
                "report_status": True,
                "generated_at": now,
                "profile_fingerprint": fingerprint,
                "prompt_version": pathway_service.PROMPT_VERSION,
                # user_saved is deliberately absent: generating must never
                # change whether the user chose to keep it.
            },
        )
        cache_delete(get_pathways_cache_key(request.user.id))
        cache_delete(get_saved_cache_key(request.user.id))
        return Response(self._pathway_payload(career, row, generated=True),
                        status=status.HTTP_200_OK)

    def _pathway_payload(self, career, row, *, generated):
        summary = (row.report or {}).get("summary") or {}
        return {
            "career_id": row.career_id,
            "title": summary.get("title") or career.jobname,
            "subtitle": summary.get("subtitle") or "",
            "total_timeline_estimate": summary.get("totalTimelineEstimate") or "",
            "current_step": pathway_service.current_step(row.report),
            "steps": summary.get("steps") or [],
            "saved": bool(row.user_saved),
            "generated_at": row.generated_at,
            "generated": generated,
            "prompt_version": row.prompt_version or pathway_service.PROMPT_VERSION,
        }

    @action(detail=True, methods=["POST", "DELETE"], url_path="pathway/save")
    def pathway_save(self, request, pk=None):
        """
        POST   /careers/{id}/pathway/save/   keep it  -> saved: true
        DELETE /careers/{id}/pathway/save/   forget it -> saved: false

        Only flips the flag. The pathway itself stays either way, so
        un-saving and re-opening costs nothing to generate again.
        """
        try:
            career_id = int(pk)
        except (TypeError, ValueError):
            raise NotFound()

        profile = self._profile_cached or self._get_or_create_profile()
        row = UserCareerReport.objects.filter(user_profile=profile, career_id=career_id).first()
        if row is None:
            return Response(
                {"status": False, "message": "No pathway for this career yet.",
                 "code": "pathway_not_generated"},
                status=status.HTTP_404_NOT_FOUND,
            )

        row.user_saved = (request.method == "POST")
        row.save(update_fields=["user_saved", "updated_at"])
        cache_delete(get_pathways_cache_key(request.user.id))
        cache_delete(get_saved_cache_key(request.user.id))

        return Response({"status": True, "career_id": career_id, "saved": row.user_saved},
                        status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"], url_path="reports")
    def reports(self, request):
        """
        The user's saved pathways, newest first.

        Only pathways the user chose to keep (user_saved) are listed. The
        table also holds pathways that were generated and never saved -
        those exist so we don't pay to generate the same thing twice, and
        the user never asked to see them here.

        Cached per user; cleared on save, unsave, delete, regeneration and
        any profile edit that changes what a pathway says.
        """
        profile = self._profile_cached or self._get_or_create_profile()

        cache_key = get_pathways_cache_key(request.user.id)
        cached = cache_get(cache_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        links = list(
            UserCareerReport.objects
            .filter(user_profile=profile, user_saved=True)
            .order_by("-updated_at")
        )
        careers = Career.objects.only(*CARD_FIELDS).in_bulk([l.career_id for l in links])
        links = [l for l in links if l.career_id in careers]

        data = CareerFilterSerializer([careers[l.career_id] for l in links], many=True).data
        for item, link in zip(data, links):
            item["my_report"] = {
                "report_status": link.report_status,
                "report": link.report or {},
                "generated_at": link.generated_at,
            }
            item["saved"] = True
        data = with_match_scores(data, match_scores(request.user, [l.career_id for l in links]))

        cache_set(cache_key, data, timeout=60 * 30)
        return Response(data, status=status.HTTP_200_OK)

    # def list(self, request, *args, **kwargs):
    #     user = request.user

    #     if not user or not user.is_authenticated:
    #         return Response([], status=status.HTTP_200_OK)

    #     profile = self._profile_cached
    #     if not profile:
    #         return Response([], status=status.HTTP_200_OK)

    #     qss = get_career_queryset(user, profile)

    #     cache_key = get_list_cache_key(user.id)
    #     cached_ids = cache.get(cache_key)

    #     # 🔥 Default fallback (always defined)
    #     careers = qss
    #     print("this is the length of the qss : ", len(qss))

    #     if cached_ids is None:
    #         print("CACHE MISS ❌")

    #         # rec_result = recommend_careers_for_user(
    #         #     user=user,
    #         #     queryset=qss,
    #         #     top_k=50,
    #         # )

    #         # # ✅ If recommendations exist
    #         # if rec_result and rec_result.get("recommendations"):

    #         #     recommended_ids = [
    #         #         item["career_id"] for item in rec_result["recommendations"]
    #         #     ]

    #         #     # 🔥 cache only IDs
    #         #     cache.set(cache_key, recommended_ids, timeout=60 * 60)

    #         #     # 🔥 preserve ranking order
    #         #     preserved_order = Case(
    #         #         *[When(id=pk, then=pos) for pos, pk in enumerate(recommended_ids)]
    #         #     )

    #         #     careers = Career.objects.filter(
    #         #         id__in=recommended_ids
    #         #     ).order_by(preserved_order)

    #         # else:
    #         #     print("Fallback running ❗")

    #         #     # 🔥 trigger embedding update (async)
    #         #     # ex = get_explored_careers(profile)
    #         #     # sv = get_saved_careers(profile)

    #         #     # 🔥 prevent duplicate heavy jobs
    #         #     if not cache.get(get_recs_lock_key(user.id)):
    #         #         cache.set(get_recs_lock_key(user.id), True, timeout=60)
    #         if cache.add(f"recs_triggered:{user.id}", True, timeout=60):
    #             print("Triggering async 🚀")
    #             precompute_recommendations_async(user.id)
    #         # cached_ids = cache.get(cache_key)

    #     else:
    #         print("CACHE HIT ✅")

    #         recommended_ids = cached_ids

    #             # 🔥 preserve ranking order
    #         preserved_order = Case(
    #             *[When(id=pk, then=pos) for pos, pk in enumerate(recommended_ids)]
    #         )

    #         careers = Career.objects.filter(
    #                 id__in=recommended_ids
    #             ).order_by(preserved_order)

    #     serializer = CareerListSerializer(
    #         careers,
    #         many=True,
    #     )

    #     return Response(serializer.data, status=status.HTTP_200_OK)

    # def list(self, request, *args, **kwargs):
    #     user = request.user

    #     if not user or not user.is_authenticated:
    #         return Response([], status=status.HTTP_200_OK)

    #     profile = self._profile_cached
    #     if not profile:
    #         return Response([], status=status.HTTP_200_OK)

    #     qss = get_career_queryset(user, profile)

    #     cache_key = get_list_cache_key(user.id)
    #     cached_ids = cache.get(cache_key)

    #     # 🔥 DEFAULT: full dataset but optimized fields
    #     careers = qss.only(
    #         "id",
    #         "sub_type",
    #         "jobname",
    #         "job_description",
    #         "dg_image_url"
            
    #     )

    #     if cached_ids is None:
    #         print("CACHE MISS ❌")

    #         # 🔒 Trigger async ONLY ONCE
    #         if cache.add(f"recs_triggered:{user.id}", True, timeout=60):
    #             print("Triggering async 🚀")
    #             update_embedding_and_recs_async(user.id)

    #         # return base queryset (full data, no limit)

    #     else:
    #         print("CACHE HIT ✅")

    #         preserved_order = Case(
    #             *[When(id=pk, then=pos) for pos, pk in enumerate(cached_ids)]
    #         )

    #         careers = Career.objects.filter(
    #             id__in=cached_ids
    #         ).only(
    #             "id",
    #             "sub_type",
    #             "jobname",
    #             "job_description",
    #             "dg_image_url"
    #         ).order_by(preserved_order)

    #     # 🔥 Use fast serializer
    #     serializer = CareerFilterSerializer(
    #         careers,
    #         many=True,
    #     )

    #     return Response(serializer.data, status=status.HTTP_200_OK)

    def list(self, request, *args, **kwargs):
        total_start = time.time()

        user = request.user

        if not user or not user.is_authenticated:
            return Response([], status=status.HTTP_200_OK)

        profile = self._profile_cached
        if not profile:
            return Response([], status=status.HTTP_200_OK)

        # Free tier: the trial is over and nothing is paid for. Keep showing
        # the careers they already explored or saved, but stop making new
        # recommendations. Off unless PAYWALL_ENFORCED is on - see
        # careers/services/free_tier.py for why.
        if paywall_enforced() and not access_for(user)["has_access"]:
            free_list = free_tier_careers(profile)
            free_data = CareerFilterSerializer(free_list, many=True).data
            free_data = with_match_scores(
                free_data, match_scores(user, [c.id for c in free_list])
            )
            return Response(free_data, status=status.HTTP_200_OK)

        t0 = time.time()
        qss = get_career_queryset(user, profile)
        logger.debug("[TIME] queryset build: %.3fs", time.time() - t0)

        cache_key = get_list_cache_key(user.id)

        t1 = time.time()
        cached_ids = cache_get(cache_key)
        logger.debug("[TIME] cache fetch: %.3fs", time.time() - t1)

        # 🔥 DEFAULT queryset
        t2 = time.time()
        # No cached recommendations yet: the user's categories (or everything),
        # one card per career - each career is stored once per label it has.
        careers = unique_careers(qss).only(*CARD_FIELDS)
        logger.debug("[TIME] queryset preparation: %.3fs", time.time() - t2)

        if cached_ids is None:
            logger.debug("CACHE MISS")

            if cache_add(f"recs_triggered:{user.id}", True, timeout=60):
                logger.debug("Triggering async embedding rebuild for user %s", user.id)
                trigger_recs_debounced(user.id)

        else:
            logger.debug("CACHE HIT")

            t3 = time.time()
            preserved_order = Case(
                *[When(id=pk, then=pos) for pos, pk in enumerate(cached_ids)]
            )

            careers = Career.objects.filter(
                id__in=cached_ids
            ).only(
                "id",
                "sub_type",
                "jobname",
                "job_description",
                "dg_image_url",
                "salary"
            ).order_by(preserved_order)

            logger.debug("[TIME] reorder queryset: %.3fs", time.time() - t3)

        # 🔥 DB FETCH happens HERE (evaluation)
        t4 = time.time()
        careers_list = list(careers)
        logger.debug("[TIME] DB fetch (query execution): %.3fs", time.time() - t4)

        # 🔥 Serialization
        t5 = time.time()
        serializer = CareerFilterSerializer(careers_list, many=True)
        data = with_match_scores(serializer.data, match_scores(user, [c.id for c in careers_list]))
        logger.debug("[TIME] serialization: %.3fs", time.time() - t5)

        total_time = time.time() - total_start
        logger.debug("[TIME] TOTAL request time: %.3fs", total_time)

        return Response(data, status=status.HTTP_200_OK)


    # @action(detail=False, methods=["GET", "POST"], url_path="filter")
    # def filter(self, request):
    #     """
    #     Filter careers using subcategories sent in request body or query params.
    #     """

    #     # 🔥 Avoid calling both unnecessarily
    #     subcategories = request.data.get("subcategories")
    #     if not subcategories:
    #         subcategories = request.query_params.getlist("subcategories")

    #     # 🔥 Base queryset (lazy, not evaluated)
    #     if not subcategories:
    #         qs = Career.objects.all().order_by("id")

    #     else:
    #         # 🔥 Normalize efficiently (no extra loops, no None issues)
    #         normalized = [norm_key(s) for s in subcategories if s]

    #         # 🔥 If normalization results empty → fallback to all (same behavior)
    #         if not normalized:
    #             qs = Career.objects.all().order_by("id")
    #         else:
    #             qs = Career.objects.filter(
    #                 normalized_sub_type__in=normalized
    #             ).order_by("id")

    #     # 🔥 Pagination (kept same)
    #     qs = self._slice(qs)

    #     # 🔥 Avoid re-evaluating queryset twice
    #     serializer = CareerFilterSerializer(qs, many=True)

    #     return Response(serializer.data, status=status.HTTP_200_OK)



    @action(detail=False, methods=["GET", "POST"], url_path="filter")
    def filter(self, request):
        """
        Guest career preview. Categories arrive in `subcategories` as display
        labels (e.g. "Healthcare"). Returns a random list with each career once:
        up to 50 per picked category, or 30 per category when none are picked.
        """
        subcategories = request.data.get("subcategories")
        if not subcategories:
            subcategories = request.query_params.getlist("subcategories")
        if isinstance(subcategories, str):
            subcategories = [subcategories]

        picked = [norm_key(s) for s in subcategories or [] if s]
        cards = guest_deck([k for k in dict.fromkeys(picked) if k])

        serializer = CareerFilterSerializer(cards, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def retrieve(self, request, *args, **kwargs):
        career = self.get_object()
        report_map = self._build_report_map([career.id])

        serializer = CareerDetailSerializer(
            career,
            context={"request": request, "report_map": report_map},
        )
        data = {**serializer.data, "match_score": match_scores(request.user, [career.id]).get(career.id)}
        return Response(data, status=status.HTTP_200_OK)

   
    def _only_city_and_subcategory_qs(self, Model, *, city: str, jobname: str):
        """
        EXACT match (case-insensitive):
          - subcategory == jobname
          - city == profile.city
        No category, no zip, no fuzzy, no geo.
        """
        # city = (getattr(profile, "city", None) or "").strip()
        city = (city or "").strip()
        sub = (jobname or "").strip()

        if not city or not sub:
            return Model.objects.none()

        # Requires Model has fields: city, subcategory
        return Model.objects.filter(subcategory__iexact=sub, city__iexact=city).order_by("-id")

    # -----------------------
    # Routes into a career: jobs / courses / apprenticeships, nearest first.
    # Each item carries distance_km / distance_miles from the user.
    # -----------------------
    def _route_items(self, request, pk, Model, serializer_class):
        # A location sent with the request (lat/lng or postcode) overrides the
        # user's own one for the sorting.
        try:
            requested = requested_origin(request)
        except PostcodeNotFound:
            return Response({"detail": "Postcode not recognised."}, status=status.HTTP_400_BAD_REQUEST)

        profile = self._profile_cached
        if not profile:
            city = (request.data.get("city") or request.query_params.get("city") or "").strip()
            origin = requested or saved_origin(city=city)
            if not city and not origin:
                return Response({"detail": "City is required."}, status=400)
            career = get_object_or_404(Career.objects.all(), pk=pk)
        else:
            city = (getattr(profile, "city", None) or "").strip()
            origin = requested or saved_origin(profile=profile, city=city)
            if not city and not origin:
                return Response({"detail": "User city not set."}, status=400)
            career = self.get_object()

        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

        if origin:
            qs = nearest_route_items(
                Model,
                jobname=jobname,
                lat=origin[0],
                lon=origin[1],
                radius_miles=parse_radius_miles(request),
                # Coordinate-less rows are only kept for the user's own city,
                # which says nothing about a location they sent.
                city="" if requested else city,
            )
        else:
            # No coordinates for the user or their city: exact city match, no distances.
            qs = self._only_city_and_subcategory_qs(Model, city=city, jobname=jobname)

        items = list(self._slice(qs))

        # Nearest-first remains the default. ?sort=relevance re-orders the
        # rows we already fetched - best title match first, distance still
        # the tie-breaker - so it costs no extra query.
        if wants_relevance(request):
            items = rank_by_relevance(
                items, jobname=jobname, radius_miles=parse_radius_miles(request)
            )

        data = serializer_class(items, many=True, context={"request": request}).data
        data = attach_distances(data, items)
        return Response(attach_relevance(data, items), status=status.HTTP_200_OK)

    @action(detail=True, methods=["GET", "POST"])
    def jobs(self, request, pk=None):
        return self._route_items(request, pk, Job, JobsSerializer)

    @action(detail=True, methods=["GET", "POST"])
    def courses(self, request, pk=None):
        return self._route_items(request, pk, Course, CoursesSerializer)

    @action(detail=True, methods=["GET", "POST"])
    def apprenticeships(self, request, pk=None):
        return self._route_items(request, pk, Apprenticeship, ApprenticeshipSerializer)


    # @action(detail=False, methods=["GET"])
    # def my(self, request):

    #     profile = self._get_or_create_profile()
    #     cache_key = get_saved_cache_key(request.user.id)

    #     cached = cache.get(cache_key)
    #     if cached:
    #         print("SAVED CACHE HIT ✅")
    #         return Response(cached, status=200)

    #     print("SAVED CACHE MISS ❌")

    #     # 🔥 Proper FK-based query
    #     qs = Career.objects.filter(
    #         saved_user_links__user_profile=profile
    #     ).order_by("-saved_user_links__created_at").distinct()

    #     career_ids = list(qs.values_list("id", flat=True))

    #     saved_map = self._build_saved_map(career_ids)
    #     # explored_map = self._build_explored_map(career_ids)
    #     report_map = self._build_report_map(career_ids)

    #     serializer = CareerListSerializer(
    #         qs,
    #         many=True,
    #         context={
    #             "request": request,
    #             "saved_map": saved_map,
    #             # "explored_map": explored_map,
    #             "report_map": report_map,
    #         },
    #     )

    #     data = serializer.data
    #     cache.set(cache_key, data, timeout=None)

    #     return Response(data, status=200)

    @action(detail=False, methods=["GET"])
    def my(self, request):

        profile = self._profile_cached or self._get_or_create_profile()
        # Ensure a freshly-created profile is cached for helpers like
        # _build_report_map (overrides any None previously cached by the
        # @cached_property descriptor).
        self._profile_cached = profile

        cache_key = get_saved_cache_key(request.user.id)

        cached = cache_get(cache_key)
        if cached:
            logger.debug("SAVED CACHE HIT")
            return Response(with_match_scores(cached, match_scores(request.user, [r["id"] for r in cached])), status=200)

        logger.debug("SAVED CACHE MISS")

        # ------------------------------------------------------------------
        # OLD: single JOIN + DISTINCT query
        # ------------------------------------------------------------------
        # Why it was replaced:
        #   This query JOINs Career with UserSavedCareer, ORDERS BY a column
        #   on the joined table, then forces a SQL DISTINCT to dedupe rows
        #   produced by the join. DISTINCT cannot use a single-column index
        #   here, so Postgres falls back to a sort-based dedupe — slow on
        #   tables with many saves.
        #
        # qs = Career.objects.filter(
        #     saved_user_links__user_profile=profile
        # ).only(
        #     "id",
        #     "sub_type",
        #     "jobname",
        #     "job_description",
        #     "dg_image_url"
        # ).order_by("-saved_user_links__created_at").distinct()
        #
        # career_ids = list(qs.values_list("id", flat=True))
        # ------------------------------------------------------------------

        # NEW: two indexed lookups — fetch ordered IDs, then hydrate Careers.
        # Step 1: get saved career IDs newest-first directly from the join
        # table (uses index on user_profile + created_at).
        career_ids = list(
            UserSavedCareer.objects
            .filter(user_profile=profile)
            .order_by("-created_at")
            .values_list("career_id", flat=True)
        )

        if not career_ids:
            cache_set(cache_key, [], timeout=60 * 60)
            return Response([], status=200)

        # Step 2: hydrate Career rows by primary key (no JOIN, no DISTINCT).
        # Preserve the order from step 1 with a Case/When expression.
        preserved_order = Case(
            *[When(id=pk, then=pos) for pos, pk in enumerate(career_ids)]
        )
        qs = Career.objects.filter(id__in=career_ids).only(
            "id",
            "sub_type",
            "jobname",
            "job_description",
            "dg_image_url",
        ).order_by(preserved_order)

        report_map = self._build_report_map(career_ids)

        serializer = CareerFilterSerializer(qs, many=True)
        data = serializer.data

        # 🔥 Inject structured report
        for item in data:
            cid = item["id"]
            link = report_map.get(cid)

            item["my_report"] = {
                "report_status": link.report_status if link else False,
                "report": link.report if link else {},
                "generated_at": link.generated_at if link else None,
            }

        cache_set(cache_key, data, timeout=60 * 60)

        return Response(with_match_scores(data, match_scores(request.user, career_ids)), status=200)
    
    # @action(detail=True, methods=["GET","POST"])
    # def save(self, request, pk=None):

    #     career = get_object_or_404(Career, pk=pk)
    #     profile = self._get_or_create_profile()

    #     UserSavedCareer.objects.get_or_create(
    #         user_profile=profile,
    #         career=career
    #     )

    #     # 🔥 cache invalidation
    #     cache.delete(get_saved_cache_key(request.user.id))
    #     cache.delete(get_list_cache_key(request.user.id))

    #     update_embedding_and_recs_async(request.user.id)

    #     serializer = CareerDetailSerializer(career)

    #     return Response(serializer.data, status=200)

    @action(detail=True, methods=["GET", "POST"])
    def save(self, request, pk=None):

        career = get_object_or_404(Career, pk=pk)
        profile = self._profile_cached or self._get_or_create_profile()

        if request.method == "POST":
            # 🔥 Save only (no heavy response)
            UserSavedCareer.objects.get_or_create(
                user_profile=profile,
                career=career
            )

            cache_delete(get_saved_cache_key(request.user.id))
            cache_delete(get_list_cache_key(request.user.id))

            self._debounced_embedding_refresh(request.user.id)

            log_activity(
                user=request.user,
                activity_type=analytics_constants.CAREER_SAVED,
                career=career,
                activity_value=career.jobname,
            )

            return Response({
                "status": True,
                "saved": True
            }, status=200)

        # 🔥 GET → return lightweight data
        serializer = CareerFilterSerializer(career)
        return Response(serializer.data, status=200)
    
    # @action(detail=True, methods=["GET","POST"])
    # def unsave(self, request, pk=None):

    #     career = get_object_or_404(Career, pk=pk)
    #     profile = self._get_or_create_profile()

    #     deleted, _ = UserSavedCareer.objects.filter(
    #         user_profile=profile,
    #         career=career
    #     ).delete()

    #     if deleted:

    #         # 🔥 cache invalidation
    #         cache.delete(get_saved_cache_key(request.user.id))
    #         cache.delete(get_list_cache_key(request.user.id))

    #         update_embedding_and_recs_async(request.user.id)

    #         return Response({"message": "Career unsaved."}, status=200)

    #     return Response(
    #         {"error": "Career was not saved."},
    #         status=404
    #     )

    @action(detail=True, methods=["GET", "POST"])
    def unsave(self, request, pk=None):

        career = get_object_or_404(Career, pk=pk)
        profile = self._profile_cached or self._get_or_create_profile()

        if request.method == "POST":
            deleted, _ = UserSavedCareer.objects.filter(
                user_profile=profile,
                career=career
            ).delete()

            if deleted:
                cache_delete(get_saved_cache_key(request.user.id))
                cache_delete(get_list_cache_key(request.user.id))

                self._debounced_embedding_refresh(request.user.id)

                log_activity(
                    user=request.user,
                    activity_type=analytics_constants.CAREER_UNSAVED,
                    career=career,
                    activity_value=career.jobname,
                )

                return Response({
                    "status": True,
                    "unsaved": True
                }, status=200)

            return Response(
                {"status": False, "message": "Career was not saved."},
                status=404
            )

        # GET → return lightweight career info
        serializer = CareerFilterSerializer(career)
        return Response(serializer.data, status=200)

    # @action(detail=False, methods=["GET"], url_path="explore_mine")
    # def explore_mine(self, request):

    #     profile = self._get_or_create_profile()
    #     cache_key = get_explored_cache_key(request.user.id)

    #     cached = cache.get(cache_key)
    #     if cached:
    #         print("EXPLORE CACHE HIT ✅")
    #         return Response(cached, status=200)

    #     print("EXPLORE CACHE MISS ❌")

    #     # 🔥 Proper FK-based query
    #     qs = Career.objects.filter(
    #         explored_user_links__user_profile=profile
    #     ).order_by("-explored_user_links__created_at").distinct()

    #     serializer = CareerListSerializer(qs, many=True)

    #     data = serializer.data
    #     cache.set(cache_key, data, timeout=None)

    #     return Response(data, status=200)
    
    # @action(detail=True, methods=["GET","POST"])
    # def explore(self, request, pk=None):

    #     career = get_object_or_404(Career, pk=pk)
    #     profile = self._get_or_create_profile()

    #     UserExploredCareer.objects.get_or_create(
    #         user_profile=profile,
    #         career=career
    #     )

    #     # 🔥 cache invalidation
    #     cache.delete(get_explored_cache_key(request.user.id))
    #     cache.delete(get_list_cache_key(request.user.id))

    #     update_embedding_and_recs_async(request.user.id)

    #     serializer = CareerDetailSerializer(career)

    #     return Response(serializer.data, status=200)

    # @action(detail=True, methods=["POST","GET"])
    # def unexplore(self, request, pk=None):

    #     career = get_object_or_404(Career, pk=pk)
    #     profile = self._get_or_create_profile()

    #     deleted, _ = UserExploredCareer.objects.filter(
    #         user_profile=profile,
    #         career=career
    #     ).delete()

    #     if deleted:
    #         # 🔥 cache invalidation
    #         cache.delete(get_explored_cache_key(request.user.id))
    #         cache.delete(get_list_cache_key(request.user.id))

    #         update_embedding_and_recs_async(request.user.id)

    #         return Response(
    #             {"message": "Career unexplored."},
    #             status=status.HTTP_200_OK
    #         )

    #     return Response(
    #         {"error": "Career was not explored."},
    #         status=status.HTTP_404_NOT_FOUND
    #     )


    @action(detail=False, methods=["GET"], url_path="explore_mine")
    def explore_mine(self, request):

        profile = self._profile_cached or self._get_or_create_profile()
        cache_key = get_explored_cache_key(request.user.id)

        cached = cache_get(cache_key)
        if cached:
            logger.debug("EXPLORE CACHE HIT")
            return Response(with_match_scores(cached, match_scores(request.user, [r["id"] for r in cached])), status=200)

        logger.debug("EXPLORE CACHE MISS")

        # ------------------------------------------------------------------
        # OLD: single JOIN + DISTINCT query (same anti-pattern as my()).
        # Replaced with a two-step ID-then-hydrate lookup that uses indexes
        # on UserExploredCareer (user_profile, created_at) instead of a
        # sort-based DISTINCT over the joined result set.
        #
        # qs = Career.objects.filter(
        #     explored_user_links__user_profile=profile
        # ).only(
        #     "id",
        #     "sub_type",
        #     "jobname",
        #     "job_description",
        #     "dg_image_url"
        # ).order_by("-explored_user_links__created_at").distinct()
        # ------------------------------------------------------------------

        # NEW: Step 1 — get explored career IDs newest-first from join table.
        career_ids = list(
            UserExploredCareer.objects
            .filter(user_profile=profile)
            .order_by("-created_at")
            .values_list("career_id", flat=True)
        )

        if not career_ids:
            cache_set(cache_key, [], timeout=60 * 60)
            return Response([], status=200)

        # Step 2 — hydrate Career rows by primary key, preserving order.
        preserved_order = Case(
            *[When(id=pk, then=pos) for pos, pk in enumerate(career_ids)]
        )
        qs = Career.objects.filter(id__in=career_ids).only(
            "id",
            "sub_type",
            "jobname",
            "job_description",
            "dg_image_url",
        ).order_by(preserved_order)

        serializer = CareerFilterSerializer(qs, many=True)  # 🔥 LIGHT
        data = serializer.data

        cache_set(cache_key, data, timeout=60 * 60)

        return Response(with_match_scores(data, match_scores(request.user, career_ids)), status=200)
    
    @action(detail=True, methods=["GET", "POST"])
    def explore(self, request, pk=None):

        career = get_object_or_404(Career, pk=pk)
        profile = self._profile_cached or self._get_or_create_profile()

        if request.method == "POST":
            UserExploredCareer.objects.get_or_create(
                user_profile=profile,
                career=career
            )

            cache_delete(get_explored_cache_key(request.user.id))
            cache_delete(get_list_cache_key(request.user.id))

            self._debounced_embedding_refresh(request.user.id)

            log_activity(
                user=request.user,
                activity_type=analytics_constants.CAREER_EXPLORED,
                career=career,
                activity_value=career.jobname,
            )

            return Response({
                "status": True,
                "explored": True
            }, status=200)

        # GET → lightweight response
        serializer = CareerFilterSerializer(career)
        return Response(serializer.data, status=200)
    
    @action(detail=True, methods=["GET", "POST"])
    def unexplore(self, request, pk=None):

        career = get_object_or_404(Career, pk=pk)
        profile = self._profile_cached or self._get_or_create_profile()

        if request.method == "POST":
            deleted, _ = UserExploredCareer.objects.filter(
                user_profile=profile,
                career=career
            ).delete()

            if deleted:
                cache_delete(get_explored_cache_key(request.user.id))
                cache_delete(get_list_cache_key(request.user.id))

                self._debounced_embedding_refresh(request.user.id)

                log_activity(
                    user=request.user,
                    activity_type=analytics_constants.CAREER_UNEXPLORED,
                    career=career,
                    activity_value=career.jobname,
                )

                return Response({
                    "status": True,
                    "unexplored": True
                }, status=200)

            return Response(
                {"status": False, "message": "Career was not explored."},
                status=404
            )

        # GET → return career info
        serializer = CareerFilterSerializer(career)
        return Response(serializer.data, status=200)
    
    @action(
    detail=False,
    methods=["POST"],
    url_path="interactions/bulk",
    permission_classes=[IsAuthenticated],
    throttle_classes=[InteractionThrottle],
    )
    def bulk_interactions(self, request):
        serializer = BulkCareerInteractionSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {
                    "status": False,
                    "message": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = self._get_or_create_profile()

        result = apply_bulk_career_interactions(
            user=request.user,
            profile=profile,
            items=serializer.validated_data["items"],
        )

        if not result["ok"]:
            return Response(
                {
                    "status": False,
                    "message": "Some career IDs are invalid.",
                    "missing_ids": result["missing_ids"],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "status": True,
                "updated_count": result["updated_count"],
                "saved_changed": result["saved_changed"],
                "explored_changed": result["explored_changed"],
            },
            status=status.HTTP_200_OK,
        )


    def get_serializer_class(self):
        if self.action in ("list", "my", "explore_mine"):
            return CareerListSerializer
        return CareerDetailSerializer
