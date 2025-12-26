# careers/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import UserProfile
from careers.models import Career, UserSavedCareer
from careers.api.serializers import CareersSerializer
from careers.api.permissions import CareerPermission


class CareersView(viewsets.ModelViewSet):
    queryset = Career.objects.all()
    serializer_class = CareersSerializer
    permission_classes = [CareerPermission]

    def _profile(self, request):
        profile, _ = UserProfile.objects.get_or_create(
            appuser=request.user,
            defaults={"age": 0},
        )
        return profile

    @action(detail=True, methods=["POST", "GET"])
    def save(self, request, pk=None):
        career = self.get_object()
        if request.method == "GET":
            return Response(self.get_serializer(career).data)

        user = self._profile(request)
        UserSavedCareer.objects.get_or_create(user_profile=user, career_id=career.id)
        return Response(self.get_serializer(career).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"])
    def my(self, request):
        user = self._profile(request)
        saved_ids = UserSavedCareer.objects.filter(user_profile=user).values_list("career_id", flat=True)
        careers = Career.objects.filter(id__in=saved_ids)
        return Response(self.get_serializer(careers, many=True).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST", "GET"])
    def unsave(self, request, pk=None):
        career = self.get_object()
        if request.method == "GET":
            return Response(self.get_serializer(career).data)

        user = self._profile(request)
        deleted, _ = UserSavedCareer.objects.filter(user_profile=user, career_id=career.id).delete()

        if deleted:
            return Response({"message": "Career unsaved."}, status=status.HTTP_200_OK)

        return Response({"error": "Career was not saved."}, status=status.HTTP_404_NOT_FOUND)
