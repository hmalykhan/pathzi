from django.urls import path
from .views import (
    SwipeStatusView,
    SwipeCareerPathView,
    UpdateSwipeLimitView
)

urlpatterns = [
    # Get swipe status
    path(
        "swipe-status/",
        SwipeStatusView.as_view(),
        name="swipe-status"
    ),

    # Record swipe
    path(
        "swipe/",
        SwipeCareerPathView.as_view(),
        name="record-swipe"
    ),

    # Update swipe limit (admin)
    path(
        "update-limit/",
        UpdateSwipeLimitView.as_view(),
        name="update-swipe-limit"
    ),
]