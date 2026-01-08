# # careers/views.py
# from rest_framework import viewsets, status
# from rest_framework.decorators import action
# from rest_framework.response import Response

# from accounts.models import UserProfile
# from careers.models import Career, UserSavedCareer
# from careers.api.serializers import CareersSerializer
# from careers.api.permissions import CareerPermission
# from django.db.models import Q
# from django.db.models.functions import Greatest, Lower
# from django.contrib.postgres.search import TrigramSimilarity


# class CareersView(viewsets.ModelViewSet):
#     queryset = Career.objects.all()
#     serializer_class = CareersSerializer
#     permission_classes = [CareerPermission]

#     def _profile(self, request):
#         profile, _ = UserProfile.objects.get_or_create(
#             appuser=request.user,
#             defaults={"age": 0},
#         )
#         return profile

#     @action(detail=True, methods=["POST", "GET"])
#     def save(self, request, pk=None):
#         career = self.get_object()
#         if request.method == "GET":
#             return Response(self.get_serializer(career).data)

#         user = self._profile(request)
#         UserSavedCareer.objects.get_or_create(user_profile=user, career_id=career.id)
#         return Response(self.get_serializer(career).data, status=status.HTTP_200_OK)

#     @action(detail=False, methods=["GET"])
#     def my(self, request):
#         user = self._profile(request)
#         saved_ids = UserSavedCareer.objects.filter(user_profile=user).values_list("career_id", flat=True)
#         careers = Career.objects.filter(id__in=saved_ids)
#         return Response(self.get_serializer(careers, many=True).data, status=status.HTTP_200_OK)

#     @action(detail=True, methods=["POST", "GET"])
#     def unsave(self, request, pk=None):
#         career = self.get_object()
#         if request.method == "GET":
#             return Response(self.get_serializer(career).data)

#         user = self._profile(request)
#         deleted, _ = UserSavedCareer.objects.filter(user_profile=user, career_id=career.id).delete()

#         if deleted:
#             return Response({"message": "Career unsaved."}, status=status.HTTP_200_OK)

#         return Response({"error": "Career was not saved."}, status=status.HTTP_404_NOT_FOUND)
    
#     def get_queryset(self):
#         if not self.request.user.is_authenticated:
#             return Career.objects.none()

#         profile = UserProfile.objects.filter(appuser=self.request.user).first()
#         if not profile:
#             return Career.objects.none()

#         # ---------- category filter (case-insensitive) ----------
#         categories = profile.category or []
#         if isinstance(categories, str):
#             categories = [categories]
#         categories = [c.strip().lower() for c in categories if c and c.strip()]
#         if not categories:
#             return Career.objects.none()

#         return Career.objects.annotate(cat_l=Lower("sub_type")).filter(cat_l__in=categories).first()



# careers/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from accounts.models import UserProfile
from careers.models import Career, UserSavedCareer
from careers.api.permissions import CareerPermission
from careers.api.serializers import CareerListSerializer, CareerDetailSerializer
from courses.api.serializer import CoursesSerializer
from courses.models import Course, UserSavedCourse
from jobs.models import Job
from jobs.api.serializers import JobsSerializer
from apprenticeship.models import Apprenticeship
from apprenticeship.api.serializers import ApprenticeshipSerializer
from django.db.models.functions import Lower



FREE_CAREER_LIMIT = 5  # you can move this to settings if you want




class CareersView(viewsets.ModelViewSet):
    serializer_class = CareerDetailSerializer
    permission_classes = [CareerPermission]

    def _is_subscribed(self, request) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_staff:
            return True

        billing = getattr(user, "billing", None)  # from BillingProfile related_name="billing"
        return bool(billing and billing.is_active)

    def _profile(self, request):
        profile, _ = UserProfile.objects.get_or_create(
            appuser=request.user,
            defaults={"age": 0},
        )
        return profile

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Career.objects.none()

        profile = UserProfile.objects.filter(appuser=self.request.user).first()
        if not profile:
            return Career.objects.none()

        # category filter (case-insensitive)
        categories = profile.category or []
        if isinstance(categories, str):
            categories = [categories]

        categories = [c.strip().lower() for c in categories if c and c.strip()]
        if not categories:
            return Career.objects.none()
        
        qs = (
            Career.objects
            .annotate(cat_l=Lower("sub_type"))
            .filter(cat_l__in=categories)
        )

        if not self._is_subscribed(self.request):
            qs = qs[:self.FREE_CAREER_LIMIT]

        return qs

        # return (
        #     Career.objects
        #     .annotate(cat_l=Lower("sub_type"))
        #     .filter(cat_l__in=categories)
        # )

    @action(detail=True, methods=["GET", "POST"])
    def save(self, request, pk=None):
        career = self.get_object()

        if request.method.lower() == "GET":
            return Response(self.get_serializer(career).data)

        user = self._profile(request)
        UserSavedCareer.objects.get_or_create(user_profile=user, career_id=career.id)
        return Response(self.get_serializer(career).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get", "POST"])
    def unsave(self, request, pk=None):
        career = self.get_object()

        if request.method.lower() == "GET":
            return Response(self.get_serializer(career).data)

        user = self._profile(request)
        deleted, _ = UserSavedCareer.objects.filter(
            user_profile=user, career_id=career.id
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

        tailored_courses = Job.objects.filter(subcategory__iexact=jobname)
        if not tailored_courses.exists():
            return Response({"detail": "No tailored jobs found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = JobsSerializer(tailored_courses, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=["GET"])
    def apprenticeships(self, request, pk=None):
        career = self.get_object()

        jobname = (career.jobname or "").strip()
        if not jobname:
            return Response({"detail": "Career subcategory missing."}, status=status.HTTP_400_BAD_REQUEST)

        tailored_courses = Apprenticeship.objects.filter(subcategory__iexact=jobname)
        if not tailored_courses.exists():
            return Response({"detail": "No tailored apprenticeshps found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = ApprenticeshipSerializer(tailored_courses, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def get_serializer_class(self):
        if self.action in ("list", "my"):
            return CareerListSerializer
        return CareerDetailSerializer

    # @action(detail=True, methods=["POST", "GET"])
    # def save(self, request, pk=None):
    #     course = get_object_or_404(Course, pk = pk)

    #     # Same as before: GET returns course data
    #     if request.method == "GET":
    #         serializer = CoursesSerializer(course, context={"request": request})
    #         return Response(serializer.data)

    #     # POST: create the link in join table
    #     user, _ = UserProfile.objects.get_or_create(appuser=request.user, defaults={"age": 0})

    #     UserSavedCourse.objects.get_or_create(
    #         user_profile=user,
    #         course_id=course.course_id,  # IMPORTANT: link by scraper UUID
    #     )

    #     serializer = CoursesSerializer(course, context={"request": request})
    #     return Response(serializer.data, status=status.HTTP_200_OK)

    # @action(detail=False, methods=["GET"])
    # def mine(self, request):
    #     # Same as before: return courses saved by current user
    #     user, _ = UserProfile.objects.get_or_create(appuser=request.user, defaults={"age": 0})

    #     saved_course_ids = UserSavedCourse.objects.filter(
    #         user_profile=user
    #     ).values_list("course_id", flat=True)

    #     courses = Course.objects.filter(course_id__in=saved_course_ids)
    #     serializer = CoursesSerializer(courses, many=True, context={"request": request})
    #     return Response(serializer.data, status=status.HTTP_200_OK)
    
    # @action(detail=True, methods=["POST", "GET"])
    # def unsave(self, request, pk=None):
    #     course = get_object_or_404(Course, pk = pk)

    #     # Same as before: GET returns course data
    #     if request.method == "GET":
    #         serializer = CoursesSerializer(course, context={"request": request})
    #         return Response(serializer.data)

    #     user, _ = UserProfile.objects.get_or_create(appuser=request.user, defaults={"age": 0})

    #     deleted_count, _ = UserSavedCourse.objects.filter(
    #         user_profile=user,
    #         course_id=course.course_id,
    #     ).delete()

    #     if deleted_count > 0:
    #         return Response({"message": "Course unsaved."}, status=status.HTTP_200_OK)

    #     return Response(
    #         {"error": "Course was not saved."},
    #         status=status.HTTP_404_NOT_FOUND,
    #     )
