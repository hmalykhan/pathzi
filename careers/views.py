# For payment method limited careers for unsubsctibed uncomment 160, 211
import re
from django.db.models import Subquery, TextField, Value
from django.db.models.functions import Cast, Coalesce, Lower, Replace, Trim
from django.utils import timezone
from django.utils.functional import cached_property
from django.shortcuts import get_object_or_404

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from accounts.models import UserProfile
from careers.models import Career, UserSavedCareer, UserExploredCareer
from careers.api.permissions import CareerPermission
from careers.api.serializers import CareerListSerializer, CareerDetailSerializer

from courses.models import Course
from courses.api.serializer import CoursesSerializer

from jobs.models import Job
from jobs.api.serializers import JobsSerializer

from apprenticeship.models import Apprenticeship
from apprenticeship.api.serializers import ApprenticeshipSerializer

from accounts.services.career_recommender import recommend_careers_for_user


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
    def _build_report_map(self, career_ids):
        """
        Return {career_id: UserSavedCareer} for current user_profile.
        Used to embed my_report per career without N+1 queries.
        """
        profile = self._profile_cached
        if not profile or not career_ids:
            return {}

        links = UserSavedCareer.objects.filter(
            user_profile=profile,
            career_id__in=career_ids,
        )
        return {l.career_id: l for l in links}

    # -----------------------
    # Careers base queryset + strict hiding of premium careers
    # -----------------------
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
            # return Career.objects.none()
            return Career.objects.all().order_by("id")

        # normalize Career.sub_type in DB the same way
        empty = Value("", output_field=TextField())
        sub = Coalesce(Cast("sub_type", output_field=TextField()), empty, output_field=TextField())
        sub = Lower(Trim(sub))
        sub = Replace(sub, Value(" ", output_field=TextField()), empty, output_field=TextField())
        sub = Replace(sub, Value("_", output_field=TextField()), empty, output_field=TextField())
        sub = Replace(sub, Value("-", output_field=TextField()), empty, output_field=TextField())
        sub = Cast(sub, output_field=TextField())

        return Career.objects.annotate(cat_l=sub).filter(cat_l__in=categories)

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
    
    # old
    # def get_object(self):
    #     """
    #     Free users must NOT access careers outside top 5.
    #     Return 404 to hide existence.
    #     """
    #     obj = super().get_object()

    #     if self._is_subscribed():
    #         return obj

    #     allowed = Career.objects.filter(id=obj.id, id__in=Subquery(self._allowed_ids_subquery())).exists()
    #     # if not allowed:
    #         # raise NotFound("Not found.")
    #     return obj

    # new
    def get_object(self):
        """
        Free users must NOT access careers outside top 5.
        Return 404 to hide existence.
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

        # ✅ everyone else: keep EXACT existing behavior
        obj = super().get_object()

        if self._is_subscribed():
            return obj

        allowed = Career.objects.filter(
            id=obj.id,
            id__in=Subquery(self._allowed_ids_subquery())
        ).exists()

        if not allowed:
            raise NotFound("Not found.")

        return obj

    @action(detail=True, methods=["GET", "PUT"], url_path="report")
    def report(self, request, pk=None):
        # Match DRF get_object() behavior: invalid pk => 404 {"detail":"Not found."}
        try:
            career_id = int(pk)
        except (TypeError, ValueError):
            raise NotFound()

        profile = self._get_or_create_profile()

        # Cheap exists check (instead of fetching the full Career row)
        if not Career.objects.filter(id=career_id).exists():
            raise NotFound()

        qs = UserSavedCareer.objects.filter(
            user_profile_id=profile.id,
            career_id=career_id,
        )

        if request.method == "GET":
            row = qs.values("report_status", "report", "generated_at").first()
            if not row:
                return Response(
                    {"detail": "Career is not saved. Save career first."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "report_status": bool(row["report_status"]),
                    "report": row["report"] or {},
                    "generated_at": row["generated_at"],
                },
                status=status.HTTP_200_OK,
            )

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

        report_data = request.data.get("report", None)
        if report_data is None:
            return Response(
                {"detail": "report is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()

        updated = qs.update(
            report=report_data,
            report_status=True,
            generated_at=now,
        )

        if updated == 0:
            return Response(
                {"detail": "Career is not saved. Save career first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "report_status": True,
                "report": report_data,
                "generated_at": now,
            },
            status=status.HTTP_200_OK,
        )

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


    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        qss = list(qs)
        print("this is the length of the qss",len(qss))
        user = request.user
        if not user or not user.is_authenticated:
            return Response([], status=status.HTTP_200_OK)

        profile = self._profile_cached
        if not profile:
            return Response([], status=status.HTTP_200_OK)
        # print("this is the profile name : ",profile.name)
        
        categories = list(profile.category)

        saved_ids = UserSavedCareer.objects.filter(
            user_profile=profile
        ).values_list("career_id", flat=True)

        # saved_careers = list(
        #     Career.objects.filter(id__in=saved_ids).distinct()
        # )

        saved_careers = list(self._filtered_base_queryset().filter(id__in=saved_ids).order_by("id"))

        # explored_careers = list(
        #     Career.objects.filter(
        #         explored_user_links__user_profile=profile
        #     ).distinct()
        # )

        explored_ids = UserExploredCareer.objects.filter(
            user_profile=profile
        ).values_list("career_id", flat=True)

        explored_careers = list(self._filtered_base_queryset().filter(id__in=explored_ids).order_by("id"))


        print("these are the saved careers of this user : ",saved_careers)
        print("thesea are the explored careers of this user : ", explored_careers)
        # bool = True
        # for category in categories:
        #     print(f"this is the categories : {category} \n ")
        #     if bool == True:
        #         print("inside\n")
        rec_result = recommend_careers_for_user(
                    user=user,
                    queryset=qss,
                    saved_careers=saved_careers,
                    explored_careers=explored_careers,
                    top_k=50,
                )
                # bool = False
            # elif bool == False:
            #     print("outside\n")
            #     rec_result["recommendations"] += recommend_careers_for_user(
            #             user=user,
            #             category=category,
            #             saved_careers=saved_careers,
            #             explored_careers=explored_careers,
            #             top_k=30,
            #         )["recommendations"]
            
        print(f"this is the len of all recomendations : {len(rec_result["recommendations"])}")

        recommended_ids = [item["career_id"] for item in rec_result["recommendations"]]

        # careers_qs = Career.objects.filter(id__in=recommended_ids)
        # careers_by_id = {career.id: career for career in careers_qs}
        careers_by_id = {
            c.id:c for c in qss if c.id in recommended_ids
        }

        careers = [
            careers_by_id[cid]
            for cid in recommended_ids
            if cid in careers_by_id
        ]

        career_ids = [c.id for c in careers]
        report_map = self._build_report_map(career_ids)
        saved_map = self._build_saved_map(career_ids)
        explored_map = self._build_explored_map(career_ids)

        serializer = CareerListSerializer(
            careers,
            many=True,
            context={
                "request": request,
                "report_map": report_map,
                "saved_map": saved_map,
                "explored_map": explored_map,
            },
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


    
    @action(detail=False, methods=["GET","POST"], url_path="filter")
    def filter(self, request):
        """
        Filter careers using subcategories sent in request body.

        Body example:
        {
            "subcategories": ["engineering", "healthcare"]
        }
        """

        subcategories = (
            request.data.get("subcategories")
            or request.query_params.getlist("subcategories")
        )

        if not subcategories:
            # return Response(
            #     {"detail": "subcategories are required."},
            #     status=status.HTTP_400_BAD_REQUEST
            # )
            qs = Career.objects.all().order_by("id")


        else:
            # normalize input
            normalized = [
                self._norm_key(s) for s in subcategories if s
            ]

            # normalize career.sub_type exactly like the main query
            empty = Value("", output_field=TextField())

            sub = Coalesce(
                Cast("sub_type", output_field=TextField()),
                empty,
                output_field=TextField()
            )

            sub = Lower(Trim(sub))
            sub = Replace(sub, Value(" ", output_field=TextField()), empty)
            sub = Replace(sub, Value("_", output_field=TextField()), empty)
            sub = Replace(sub, Value("-", output_field=TextField()), empty)
            sub = Cast(sub, output_field=TextField())

            qs = Career.objects.annotate(cat_l=sub).filter(cat_l__in=normalized)

        qs = self._slice(qs)

        careers = list(qs)

        report_map = self._build_report_map([c.id for c in careers])

        serializer = CareerListSerializer(
            careers,
            many=True,
            context={"request": request, "report_map": report_map},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def retrieve(self, request, *args, **kwargs):
        career = self.get_object()
        report_map = self._build_report_map([career.id])

        serializer = CareerDetailSerializer(
            career,
            context={"request": request, "report_map": report_map},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    # -----------------------
    # Actions: save / unsave / my (unchanged)
    # -----------------------
    @action(detail=False, methods=["GET"])
    def my(self, request):
        profile = self._get_or_create_profile()

        saved_ids = UserSavedCareer.objects.filter(
            user_profile=profile
        ).values_list("career_id", flat=True)

        qs = Career.objects.filter(id__in=saved_ids).order_by("id")

        if not self._is_subscribed():
            qs = qs.filter(id__in=Subquery(self._allowed_ids_subquery()))

        # old
        # careers = list(qs)
        # report_map = self._build_report_map([c.id for c in careers])

        # serializer = CareerListSerializer(
        #     careers,
        #     many=True,
        #     context={"request": request, "report_map": report_map},
        # )

        # new
        careers = list(qs)
        career_ids = [c.id for c in careers]

        saved_map = self._build_saved_map(career_ids)
        explored_map = self._build_explored_map(career_ids)
        report_map = self._build_report_map(career_ids)

        serializer = CareerListSerializer(
            careers,
            many=True,
            context={
                "request": request,
                "saved_map": saved_map,
                "explored_map": explored_map,
                "report_map": report_map,
            },
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST", "GET"])
    def save(self, request, pk=None):
        career = self.get_object()
        profile = self._get_or_create_profile()

        link, _ = UserSavedCareer.objects.get_or_create(
            user_profile=profile,
            career_id=career.id,
        )

        # old
        # serializer = CareerDetailSerializer(
        #     career,
        #     context={"request": request, "report_map": {career.id: link}},
        # )

        # new
        career_ids = [career.id]
        saved_map = self._build_saved_map(career_ids)
        explored_map = self._build_explored_map(career_ids)
        report_map = {career.id: link}

        serializer = CareerDetailSerializer(
            career,
            context={
                "request": request,
                "saved_map": saved_map,
                "explored_map": explored_map,
                "report_map": report_map,
            },
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST", "GET"])
    def unsave(self, request, pk=None):
        career = self.get_object()
        profile = self._get_or_create_profile()
        deleted, _ = UserSavedCareer.objects.filter(
            user_profile=profile,
            career_id=career.id
        ).delete()

        if deleted:
            return Response({"message": "Career unsaved."}, status=status.HTTP_200_OK)
        return Response({"error": "Career was not saved."}, status=status.HTTP_404_NOT_FOUND)

    # -----------------------
    # ✅ NEW: Only match (profile.city + career.jobname/subcategory) and nothing else
    # -----------------------
    # def _only_city_and_subcategory_qs(self, Model, *, profile: UserProfile, jobname: str):
    #     """
    #     EXACT match (case-insensitive):
    #       - subcategory == jobname
    #       - city == profile.city
    #     No category, no zip, no fuzzy, no geo.
    #     """
    #     city = (getattr(profile, "city", None) or "").strip()
    #     sub = (jobname or "").strip()

    #     if not city or not sub:
    #         return Model.objects.none()

    #     # Requires Model has fields: city, subcategory
    #     return Model.objects.filter(subcategory__iexact=sub, city__iexact=city).order_by("-id")

    # @action(detail=True, methods=["GET"])
    # def jobs(self, request, pk=None):
    #     career = self.get_object()
    #     jobname = (career.jobname or "").strip()
    #     if not jobname:
    #         return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     profile = self._profile_cached
    #     if not profile:
    #         return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     qs = self._only_city_and_subcategory_qs(Job, profile=profile, jobname=jobname)
    #     qs = self._slice(qs)

    #     data = JobsSerializer(list(qs), many=True, context={"request": request}).data
    #     return Response(data, status=status.HTTP_200_OK)

    # @action(detail=True, methods=["GET"])
    # def courses(self, request, pk=None):
    #     career = self.get_object()
    #     jobname = (career.jobname or "").strip()
    #     if not jobname:
    #         return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     profile = self._profile_cached
    #     if not profile:
    #         return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     qs = self._only_city_and_subcategory_qs(Course, profile=profile, jobname=jobname)
    #     qs = self._slice(qs)

    #     data = CoursesSerializer(list(qs), many=True, context={"request": request}).data
    #     return Response(data, status=status.HTTP_200_OK)

    # @action(detail=True, methods=["GET"])
    # def apprenticeships(self, request, pk=None):
    #     career = self.get_object()
    #     jobname = (career.jobname or "").strip()
    #     if not jobname:
    #         return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     profile = self._profile_cached
    #     if not profile:
    #         return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)

    #     qs = self._only_city_and_subcategory_qs(Apprenticeship, profile=profile, jobname=jobname)
    #     qs = self._slice(qs)

    #     data = ApprenticeshipSerializer(list(qs), many=True, context={"request": request}).data
    #     return Response(data, status=status.HTTP_200_OK)

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

    # @action(detail=True, methods=["GET"])
    @action(detail=True, methods=["GET","POST"])
    def jobs(self, request, pk=None):
        profile = self._profile_cached
        if not profile:
            # return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)
            city = (
            request.data.get("city")
            or request.query_params.get("city")
            )
            if not city:
                return Response({"detail": "City is required."}, status=400)
            career = get_object_or_404(Career.objects.all(), pk=pk)

        else :
            city = (getattr(profile, "city", None) or "").strip()
            if not city:
                return Response({"detail": "User city not set."}, status=400)
            career = self.get_object()

        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)
        # qs = self._only_city_and_subcategory_qs(Job, profile=profile, jobname=jobname)
        qs = self._only_city_and_subcategory_qs(Job, city=city, jobname=jobname)
        qs = self._slice(qs)

        data = JobsSerializer(list(qs), many=True, context={"request": request}).data
        return Response(data, status=status.HTTP_200_OK)

    # @action(detail=True, methods=["GET"])
    @action(detail=True, methods=["GET","POST"])
    def courses(self, request, pk=None):
        profile = self._profile_cached
        if not profile:
            # return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)
            city = (
            request.data.get("city")
            or request.query_params.get("city")
            )
            if not city:
                return Response({"detail": "City is required."}, status=400)
            career = get_object_or_404(Career.objects.all(), pk=pk)
        else:
            city = (getattr(profile, "city", None) or "").strip()
            if not city:
                return Response({"detail": "User city not set."}, status=400)
            career = self.get_object()


        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)
        # qs = self._only_city_and_subcategory_qs(Course, profile=profile, jobname=jobname)
        qs = self._only_city_and_subcategory_qs(Course, city=city, jobname=jobname)
        qs = self._slice(qs)

        data = CoursesSerializer(list(qs), many=True, context={"request": request}).data
        return Response(data, status=status.HTTP_200_OK)

    # @action(detail=True, methods=["GET"])
    @action(detail=True, methods=["GET","POST"])
    def apprenticeships(self, request, pk=None):
        profile = self._profile_cached
        if not profile:
            # return Response({"detail": "User profile missing."}, status=status.HTTP_400_BAD_REQUEST)
            city = (
            request.data.get("city")
            or request.query_params.get("city")
            )
            if not city:
                return Response({"detail": "City is required."}, status=400)
            career = get_object_or_404(Career.objects.all(), pk=pk)
        else:
            city = (getattr(profile, "city", None) or "").strip()
            if not city:
                return Response({"detail": "User city not set."}, status=400)
            career = self.get_object()

        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)
        # qs = self._only_city_and_subcategory_qs(Apprenticeship, profile=profile, jobname=jobname)
        qs = self._only_city_and_subcategory_qs(Apprenticeship, city=city, jobname=jobname)
        qs = self._slice(qs)

        data = ApprenticeshipSerializer(list(qs), many=True, context={"request": request}).data
        return Response(data, status=status.HTTP_200_OK)


    @action(detail=False, methods=["GET"], url_path="explore_mine")
    def explore_mine(self, request):
        profile = self._get_or_create_profile()

        explored_ids = UserExploredCareer.objects.filter(
            user_profile=profile
        ).values_list("career_id", flat=True)

        # qs = self._filtered_base_queryset().filter(id__in=explored_ids).order_by("id")
        qs = Career.objects.filter(id__in=explored_ids).order_by("id")

        # if not self._is_subscribed():
        #     qs = qs.filter(id__in=Subquery(self._allowed_ids_subquery()))
        # old
        # careers = list(qs)
        # report_map = self._build_report_map([c.id for c in careers])

        # serializer = CareerListSerializer(
        #     careers,
        #     many=True,
        #     context={"request": request, "report_map": report_map},
        # )

        # new
        careers = list(qs)
        career_ids = [c.id for c in careers]

        saved_map = self._build_saved_map(career_ids)
        explored_map = self._build_explored_map(career_ids)
        report_map = self._build_report_map(career_ids)

        serializer = CareerListSerializer(
            careers,
            many=True,
            context={
                "request": request,
                "saved_map": saved_map,
                "explored_map": explored_map,
                "report_map": report_map,
            },
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


    @action(detail=True, methods=["POST", "GET"])
    def explore(self, request, pk=None):
        career = self.get_object()
        profile = self._get_or_create_profile()

        UserExploredCareer.objects.get_or_create(
            user_profile=profile,
            career_id=career.id,
        )

        # old
        # report_map = self._build_report_map([career.id])

        # serializer = CareerDetailSerializer(
        #     career,
        #     context={"request": request, "report_map": report_map},
        # )

        # new
        career_ids = [career.id]
        saved_map = self._build_saved_map(career_ids)
        explored_map = self._build_explored_map(career_ids)
        report_map = self._build_report_map(career_ids)

        serializer = CareerDetailSerializer(
            career,
            context={
                "request": request,
                "saved_map": saved_map,
                "explored_map": explored_map,
                "report_map": report_map,
            },
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


    @action(detail=True, methods=["POST", "GET"])
    def unexplore(self, request, pk=None):
        career = self.get_object()
        profile = self._get_or_create_profile()

        deleted, _ = UserExploredCareer.objects.filter(
            user_profile=profile,
            career_id=career.id
        ).delete()

        if deleted:
            return Response({"message": "Career unexplored."}, status=status.HTTP_200_OK)

        return Response(
            {"error": "Career was not explored."},
            status=status.HTTP_404_NOT_FOUND
        )


    def get_serializer_class(self):
        if self.action in ("list", "my", "explore_mine"):
            return CareerListSerializer
        return CareerDetailSerializer
