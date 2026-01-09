import re

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from django.db.models import Q, Case, When, Value, IntegerField, TextField
from django.db.models.functions import Lower, Replace, Trim, Coalesce, Cast

from accounts.models import UserProfile
from .models import Course, UserSavedCourse
from .api.serializer import CoursesSerializer
from .api.permissions import CoursePermission


class CoursesView(viewsets.ModelViewSet):
    queryset = Course.objects.all()
    serializer_class = CoursesSerializer
    permission_classes = [CoursePermission]

    @action(detail=True, methods=["POST", "GET"])
    def save(self, request, pk=None):
        course = self.get_object()

        if request.method == "GET":
            return Response(self.get_serializer(course).data)

        # keep your existing behavior: require profile exists (404 if missing)
        user = get_object_or_404(UserProfile, appuser=request.user)

        UserSavedCourse.objects.get_or_create(
            user_profile=user,
            course_id=course.course_id,
        )

        return Response(self.get_serializer(course).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"])
    def my(self, request):
        user, _ = UserProfile.objects.get_or_create(appuser=request.user, defaults={"age": 0})

        saved_course_ids = UserSavedCourse.objects.filter(
            user_profile=user
        ).values_list("course_id", flat=True)

        courses = Course.objects.filter(course_id__in=saved_course_ids)
        return Response(self.get_serializer(courses, many=True).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST", "GET"])
    def unsave(self, request, pk=None):
        course = self.get_object()

        if request.method == "GET":
            return Response(self.get_serializer(course).data)

        user, _ = UserProfile.objects.get_or_create(appuser=request.user, defaults={"age": 0})

        deleted_count, _ = UserSavedCourse.objects.filter(
            user_profile=user,
            course_id=course.course_id,
        ).delete()

        if deleted_count > 0:
            return Response({"message": "Course unsaved."}, status=status.HTTP_200_OK)

        return Response({"error": "Course was not saved."}, status=status.HTTP_404_NOT_FOUND)

    def get_queryset(self):
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return Course.objects.none()

        profile = UserProfile.objects.filter(appuser=user).first()
        if not profile:
            return Course.objects.none()

        # ---------- category filter (case-insensitive) ----------
        categories = profile.category or []
        if isinstance(categories, str):
            categories = [categories]
        categories = [c.strip().lower() for c in categories if c and c.strip()]
        if not categories:
            return Course.objects.none()

        base_qs = Course.objects.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

        # ---------- build words from country/city/zip ----------
        country = (getattr(profile, "country", None) or "").strip().lower()
        city = (getattr(profile, "city", None) or "").strip().lower()
        postal = (getattr(profile, "zip_code", None) or "").strip().lower()

        profile_text = " ".join([x for x in [country, city, postal] if x])
        words = [w for w in re.split(r"[^a-z0-9]+", profile_text) if w]
        words = list(dict.fromkeys(words))  # dedupe keep order

        if not words:
            return Course.objects.none()

        THRESHOLD = 2 if len(words) >= 2 else 1

        # ---------- normalize course address to loc_n ----------
        empty_text = Value("", output_field=TextField())
        addr = Coalesce(Cast("address", output_field=TextField()), empty_text, output_field=TextField())
        addr = Lower(Trim(addr))

        # remove spaces + common separators (same logic you had)
        for ch in [" ", "\n", "\t", "\r", ",", ".", "-", "/", "#"]:
            addr = Replace(
                addr,
                Value(ch, output_field=TextField()),
                empty_text,
                output_field=TextField(),
            )

        addr = Cast(addr, output_field=TextField())

        qs = base_qs.annotate(loc_n=addr).exclude(loc_n="")

        # ---------- match_count = number of words found in loc_n ----------
        match_expr = Value(0, output_field=IntegerField())
        for w in words:
            match_expr += Case(
                When(loc_n__contains=w, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )

        qs = qs.annotate(match_count=match_expr)

        return qs.filter(match_count__gte=THRESHOLD).order_by("-match_count")
