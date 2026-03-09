from django.db import transaction
from django.contrib.auth import get_user_model


from rest_framework.generics import GenericAPIView
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from usage_limits.models import CareerSwipeUsage
from usage_limits.api.serializers import SwipeStatusSerializer, UpdateSwipeSerializer

User = get_user_model()


class SwipeStatusView(APIView):
    """
    Returns swipe usage.
    Works in two modes:
    1. Normal user -> uses JWT (request.user)
    2. Admin -> can pass user_id
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):

        user_id = request.query_params.get("user_id")

        # Admin querying another user
        if user_id and request.user.is_staff:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response(
                    {"detail": "User not found"},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            user = request.user

        usage, created = CareerSwipeUsage.objects.get_or_create(user=user)

        serializer = SwipeStatusSerializer(usage)

        return Response(serializer.data)


class SwipeCareerPathView(APIView):
    """
    Records swipe.
    Normal users -> JWT user
    Admin -> optional user_id
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):

        user_id = request.data.get("user_id")

        if user_id and request.user.is_staff:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response(
                    {"detail": "User not found"},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            user = request.user

        with transaction.atomic():

            usage, created = CareerSwipeUsage.objects.select_for_update().get_or_create(
                user=user
            )

            if usage.swipes_used >= usage.max_swipes:
                return Response(
                    {"detail": "Swipe limit reached"},
                    status=status.HTTP_403_FORBIDDEN
                )

            usage.swipes_used += 1
            usage.save()

            remaining_swipes = usage.max_swipes - usage.swipes_used

        return Response({
            "message": "Swipe recorded",
            "remaining_swipes": remaining_swipes
        })


class UpdateSwipeLimitView(GenericAPIView):

    permission_classes = [IsAuthenticated]
    serializer_class = UpdateSwipeSerializer

    def patch(self, request):

        serializer = self.get_serializer(
            data=request.data,
            context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        usage, _ = CareerSwipeUsage.objects.get_or_create(user=request.user)

        if "swipes_used" in serializer.validated_data:
            usage.swipes_used = serializer.validated_data["swipes_used"]

        if "max_swipes" in serializer.validated_data:
            usage.max_swipes = serializer.validated_data["max_swipes"]

        usage.save()

        return Response(SwipeStatusSerializer(usage).data)