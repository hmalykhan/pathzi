from rest_framework import viewsets
from accounts.models import UserProfile
from .models import Course
from .api.serializer import CoursesSerializer
from .api.permissions import CoursePermission
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
class CoursesView(viewsets.ModelViewSet):
    queryset = Course.objects.all()
    serializer_class = CoursesSerializer
    permission_classes = [CoursePermission]

    @action(detail=True, methods=["POST","GET"])
    def save(self, request, pk=None):
        course = self.get_object()
        serializer = self.get_serializer(course)
        if request.method == "GET":
            return Response(serializer.data)
        user = get_object_or_404(UserProfile, appuser=self.request.user)
        course.user_profile.add(user)
        return Response(serializer.data)

    @action(detail=False, methods=["GET"])
    def my(self, request):
        course = Course.objects.filter(user_profile__appuser=request.user)
        serializer = self.get_serializer(course, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=["POST","GET"])
    def unsave(self, request, pk=None):
        course = self.get_object()
        if request.method == "GET":
            serializer = self.get_serializer(course)
            return Response(serializer.data)
        user = get_object_or_404(UserProfile, appuser=self.request.user)
        if course.user_profile.filter(pk = user.pk).exists():
            course.user_profile.remove(user)
            return Response({'message':'the user has been delete'})
        return Response({'error':'no user found in this job.'},status=status.HTTP_404_NOT_FOUND)

    # @action(detail=False, methods=["GET"])
    # def all(self, request):
    #     course = Course.objects.filter(user_profile__appuser = request.user)
    #     serializer = self.get_serializer(course, many=True)
    #     return Response({"data":serializer.data, })
    
    # @action(detail=False, methods=["POST"])
    # def add(self, request):
    #     serializer = self.get_serializer(data=request.data)
    #     serializer.is_valid(raise_exception=True)
    #     serializer.save(user_profile=[UserProfile.objects.get(appuser=request.user)])
    #     return Response({"message":f"""course has been added to the user {request.user}""","data":serializer.data})
    
    # @action(detail=False, methods=["GET","PATCH"], url_path="edit(?:/(?P<pk>[^/.]+))?")
    # def edit(self, request, pk=None):
    #     try:
    #         course = Course.objects.get(pk=pk,user_profile__appuser=request.user)
    #     except Course.DoesNotExist:
    #         return Response({"error":"the course does not found."}, status=status.HTTP_404_NOT_FOUND)
    #     if request.method == "GET":
    #         serializer = self.get_serializer(course)
    #         return Response({'data':serializer.data})
    #     serializer = self.get_serializer(course, data=request.data, partial=True)
    #     serializer.is_valid(raise_exception=True)
    #     serializer.save()
    #     return Response({"message":f"""course has been updated to the user {request.user}""","data":serializer.data})
    
    # @action(detail=False, methods=["GET","DELETE"], url_path="delete(?:/(?P<pk>[^/.]+))?")
    # def delete(self, request, pk=None):
    #     try:
    #         course = Course.objects.get(pk=pk,user_profile__appuser=request.user)
    #     except Course.DoesNotExist:
    #         return Response({"error":"the course does not found."}, status=status.HTTP_404_NOT_FOUND)
    #     if request.method == "GET":
    #         serializer = self.get_serializer(course)
    #         return Response({'data':serializer.data})
    #     course.delete()
    #     return Response({"message":"qualification has been deleted"},status=status.HTTP_200_OK)