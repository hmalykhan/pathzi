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

from accounts.models import UserProfile
from careers.models import Career, UserSavedCareer
from careers.api.permissions import CareerPermission
from careers.api.serializers import CareerListSerializer, CareerDetailSerializer


from django.db.models.functions import Lower


class CareersView(viewsets.ModelViewSet):
    serializer_class = CareerDetailSerializer
    permission_classes = [CareerPermission]

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

        return (
            Career.objects
            .annotate(cat_l=Lower("sub_type"))
            .filter(cat_l__in=categories)
        )

    @action(detail=True, methods=["get", "post"])
    def save(self, request, pk=None):
        career = self.get_object()

        if request.method.lower() == "get":
            return Response(self.get_serializer(career).data)

        user = self._profile(request)
        UserSavedCareer.objects.get_or_create(user_profile=user, career_id=career.id)
        return Response(self.get_serializer(career).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get", "post"])
    def unsave(self, request, pk=None):
        career = self.get_object()

        if request.method.lower() == "get":
            return Response(self.get_serializer(career).data)

        user = self._profile(request)
        deleted, _ = UserSavedCareer.objects.filter(
            user_profile=user, career_id=career.id
        ).delete()

        if deleted:
            return Response({"message": "Career unsaved."}, status=status.HTTP_200_OK)

        return Response({"error": "Career was not saved."}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=["get"])
    def my(self, request):
        user = self._profile(request)
        saved_ids = UserSavedCareer.objects.filter(
            user_profile=user
        ).values_list("career_id", flat=True)

        careers = Career.objects.filter(id__in=saved_ids)
        return Response(self.get_serializer(careers, many=True).data, status=status.HTTP_200_OK)
    # @action(detail=False, method=['get'])
    # def tailored_jobs(self, request, pk=None):
    #     # self.get_object(pk = pk)
    
    def get_serializer_class(self):
        if self.action in ("list", "my"):
            return CareerListSerializer
        return CareerDetailSerializer
