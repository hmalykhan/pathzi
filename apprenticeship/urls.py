# apprenticeship/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ApprenticeshipView

router = DefaultRouter()
router.register("", ApprenticeshipView, basename="Apprenticeship")

urlpatterns = [
    path("", include(router.urls)),
]
