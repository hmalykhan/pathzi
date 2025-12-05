from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import QualificationVeiw
router = DefaultRouter()
router.register('qualifications',QualificationVeiw, basename='qualifications')
urlpatterns = [
path('', include(router.urls)),
]