# careers/views.py
from django.db.models.functions import Lower
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import UserProfile
from careers.models import Career, UserSavedCareer
from careers.api.permissions import CareerPermission
from careers.api.serializers import CareerListSerializer, CareerDetailSerializer

from courses.api.serializer import CoursesSerializer
from courses.models import Course
from jobs.models import Job
from jobs.api.serializers import JobsSerializer
from apprenticeship.models import Apprenticeship
from apprenticeship.api.serializers import ApprenticeshipSerializer


FREE_CAREER_LIMIT = 5  # move to settings if you want


class CareersView(viewsets.ModelViewSet):
    serializer_class = CareerDetailSerializer
    permission_classes = [CareerPermission]

    # -----------------------
    # Helpers
    # -----------------------
    def _is_subscribed(self, request) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_staff:
            return True

        billing = getattr(user, "billing", None)  # BillingProfile related_name="billing"
        return bool(billing and billing.is_active)

    def _profile(self, request):
        profile, _ = UserProfile.objects.get_or_create(
            appuser=request.user,
            defaults={"age": 0},
        )
        return profile

    def _filtered_base_queryset(self):
        """
        Returns the category-filtered Career queryset for the current user.
        Does NOT apply free-limit slicing here (so we can use it consistently).
        """
        if not self.request.user.is_authenticated:
            return Career.objects.none()

        profile = UserProfile.objects.filter(appuser=self.request.user).first()
        if not profile:
            return Career.objects.none()

        categories = profile.category or []
        if isinstance(categories, str):
            categories = [categories]

        categories = [c.strip().lower() for c in categories if c and c.strip()]
        if not categories:
            return Career.objects.none()

        return (
            Career.objects
            .annotate(cat_l=Lower("sub_type"))
            .filter(cat_l__in=categories)
        )

    def _apply_free_limit_if_needed(self, qs):
        """
        Apply deterministic ordering + slicing for free users.
        """
        if self._is_subscribed(self.request):
            return qs

        # IMPORTANT: always order before slicing so results are stable
        return qs.order_by("id")[:FREE_CAREER_LIMIT]

    # -----------------------
    # Queryset
    # -----------------------
    def get_queryset(self):
        qs = self._filtered_base_queryset()

        # Apply the free limit ONLY for list-ish usage (list + my)
        # For retrieve/detail, we enforce strict guard in get_object below.
        if self.action in ("list", "my"):
            qs = self._apply_free_limit_if_needed(qs)

        return qs

    # -----------------------
    # Optional strict detail guard
    # -----------------------
    def get_object(self):
        """
        If user is NOT subscribed, they should only be able to retrieve careers
        within their free 5. This blocks direct opening of premium career IDs.
        """
        obj = super().get_object()

        if self._is_subscribed(self.request):
            return obj

        # For free users, ensure obj is inside the top 5 (same filter + ordering)
        allowed_ids = list(
            self._filtered_base_queryset()
            .order_by("id")
            .values_list("id", flat=True)[:FREE_CAREER_LIMIT]
        )

        if obj.id not in allowed_ids:
            # 403 is more accurate than 404 (exists but not allowed)
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Active subscription required to access this career.")

        return obj

    # -----------------------
    # Actions: save/unsave/my
    # -----------------------
    @action(detail=True, methods=["GET", "POST"])
    def save(self, request, pk=None):
        career = self.get_object()

        if request.method.lower() == "get":
            return Response(self.get_serializer(career).data)

        user = self._profile(request)
        UserSavedCareer.objects.get_or_create(user_profile=user, career_id=career.id)
        return Response(self.get_serializer(career).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["GET", "POST"])
    def unsave(self, request, pk=None):
        career = self.get_object()

        if request.method.lower() == "get":
            return Response(self.get_serializer(career).data)

        user = self._profile(request)
        deleted, _ = UserSavedCareer.objects.filter(
            user_profile=user,
            career_id=career.id,
        ).delete()

        if deleted:
            return Response({"message": "Career unsaved."}, status=status.HTTP_200_OK)

        return Response({"error": "Career was not saved."}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=["GET"])
    def my(self, request):
        user = self._profile(request)
        saved_ids = UserSavedCareer.objects.filter(
            user_profile=user
        ).values_list("career_id", flat=True)

        careers = self.get_queryset().filter(id__in=saved_ids)
        return Response(self.get_serializer(careers, many=True).data, status=status.HTTP_200_OK)

    # -----------------------
    # Career → related items by jobname/subcategory
    # -----------------------
    @action(detail=True, methods=["GET"])
    def courses(self, request, pk=None):
        career = self.get_object()

        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

        tailored_courses = Course.objects.filter(subcategory__iexact=jobname)
        if not tailored_courses.exists():
            return Response({"detail": "No tailored courses found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = CoursesSerializer(tailored_courses, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["GET"])
    def jobs(self, request, pk=None):
        career = self.get_object()

        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

        tailored_jobs = Job.objects.filter(subcategory__iexact=jobname)
        if not tailored_jobs.exists():
            return Response({"detail": "No tailored jobs found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = JobsSerializer(tailored_jobs, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["GET"])
    def apprenticeships(self, request, pk=None):
        career = self.get_object()

        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

        tailored_apps = Apprenticeship.objects.filter(subcategory__iexact=jobname)
        if not tailored_apps.exists():
            return Response({"detail": "No tailored apprenticeshps found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = ApprenticeshipSerializer(tailored_apps, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    # -----------------------
    # Serializer switching
    # -----------------------
    def get_serializer_class(self):
        if self.action in ("list", "my"):
            return CareerListSerializer
        return CareerDetailSerializer
