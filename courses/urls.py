from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CoursesView
router = DefaultRouter()
router.register('',CoursesView, basename='courses')
urlpatterns = [
    path('',include(router.urls))
]
