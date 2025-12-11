from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import JobsView

router = DefaultRouter()
router.register('',JobsView, basename='Jobs')

urlpatterns = [
    path('',include(router.urls))
]

