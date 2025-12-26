# apprenticeship/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import UserProfile
from apprenticeship.models import Apprenticeship, UserSavedApprenticeship
from apprenticeship.api.serializers import ApprenticeshipSerializer
from apprenticeship.api.permissions import ApprenticeshipPermission


class ApprenticeshipView(viewsets.ModelViewSet):
    queryset = Apprenticeship.objects.all()
    serializer_class = ApprenticeshipSerializer
    permission_classes = [ApprenticeshipPermission]

    def _profile(self, request):
        # avoids UserProfile.DoesNotExist
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
        return Response(
            self.get_serializer(apprenticeship).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["GET"])
    def my(self, request):
        user = self._profile(request)
        saved_refs = UserSavedApprenticeship.objects.filter(
            user_profile=user
        ).values_list("vacancy_ref", flat=True)

        apprenticeships = Apprenticeship.objects.filter(vacancy_ref__in=saved_refs)
        return Response(
            self.get_serializer(apprenticeships, many=True).data,
            status=status.HTTP_200_OK,
        )

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
            return Response(
                {"message": "Apprenticeship unsaved."},
                status=status.HTTP_200_OK,
            )

        return Response(
            {"error": "Apprenticeship was not saved."},
            status=status.HTTP_404_NOT_FOUND,
        )
