import re

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import UserProfile
from apprenticeship.models import Apprenticeship, UserSavedApprenticeship
from apprenticeship.api.serializers import ApprenticeshipSerializer
from apprenticeship.api.permissions import ApprenticeshipPermission

from django.db.models import Q, Value, TextField, IntegerField, Case, When
from django.db.models.functions import Lower, Replace, Trim, Coalesce, Cast, Greatest
from django.contrib.postgres.search import TrigramSimilarity


class ApprenticeshipView(viewsets.ModelViewSet):
    queryset = Apprenticeship.objects.all()
    serializer_class = ApprenticeshipSerializer
    permission_classes = [ApprenticeshipPermission]

    def _profile(self, request):
        profile, _ = UserProfile.objects.get_or_create(
            appuser=request.user,
            defaults={"age": 0},
        )
        return profile

    @action(detail=True, methods=["POST", "GET"])
    def save(self, request, pk=None):
        apprenticeship = self.get_object()
        if request.method == "GET":
            return Response(self.get_serializer(apprenticeship).data)

        user = self._profile(request)
        UserSavedApprenticeship.objects.get_or_create(
            user_profile=user,
            vacancy_ref=apprenticeship.vacancy_ref,
        )
        return Response(self.get_serializer(apprenticeship).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"])
    def my(self, request):
        user = self._profile(request)
        saved_refs = UserSavedApprenticeship.objects.filter(
            user_profile=user
        ).values_list("vacancy_ref", flat=True)

        apprenticeships = Apprenticeship.objects.filter(vacancy_ref__in=saved_refs)
        return Response(self.get_serializer(apprenticeships, many=True).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST", "GET"])
    def unsave(self, request, pk=None):
        apprenticeship = self.get_object()
        if request.method == "GET":
            return Response(self.get_serializer(apprenticeship).data)

        user = self._profile(request)
        deleted, _ = UserSavedApprenticeship.objects.filter(
            user_profile=user,
            vacancy_ref=apprenticeship.vacancy_ref,
        ).delete()

        if deleted:
            return Response({"message": "Apprenticeship unsaved."}, status=status.HTTP_200_OK)

        return Response({"error": "Apprenticeship was not saved."}, status=status.HTTP_404_NOT_FOUND)


    # def get_queryset(self):
    #     user = getattr(self.request, "user", None)
    #     if not user or not user.is_authenticated:
    #         return Apprenticeship.objects.none()

    #     profile = UserProfile.objects.filter(appuser=user).first()
    #     if not profile:
    #         return Apprenticeship.objects.none()

    #     # ------------------- 1) subcategory filter -------------------
    #     # Tries profile.subcategory first; falls back to profile.category (your old behavior)
    #     subcats = getattr(profile, "subcategory", None) or getattr(profile, "subcategories", None) or profile.category or []
    #     if isinstance(subcats, str):
    #         subcats = [subcats]
    #     subcats = [s.strip().lower() for s in subcats if s and str(s).strip()]
    #     if not subcats:
    #         return Apprenticeship.objects.none()

    #     base_qs = (
    #         Apprenticeship.objects
    #         .annotate(sub_l=Lower("subcategory"))
    #         .filter(sub_l__in=subcats)
    #     )

    #     # ------------------- 2) strict city match -------------------
    #     profile_city = getattr(profile, "city", None)
    #     if not profile_city or not str(profile_city).strip():
    #         return Apprenticeship.objects.none()

    #     # normalize profile city: lowercase + remove spaces/separators
    #     pc = str(profile_city).strip().lower()
    #     pc = re.sub(r"[^a-z0-9]+", "", pc)  # removes spaces + punctuation

    #     empty_text = Value("", output_field=TextField())

    #     # normalize DB city the same way (lowercase + remove spaces/separators)
    #     db_city = Coalesce(Cast("city", output_field=TextField()), empty_text, output_field=TextField())
    #     db_city = Lower(Trim(db_city))

    #     # remove common separators (rough equivalent of regex, but DB-safe)
    #     for ch in [" ", "\n", "\t", "\r", ",", ".", "-", "/", "#"]:
    #         db_city = Replace(db_city, Value(ch, output_field=TextField()), empty_text, output_field=TextField())

    #     qs = base_qs.annotate(city_n=db_city)

    #     # exact match after normalization
    #     return qs.filter(city_n=pc)
