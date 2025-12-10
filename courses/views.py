from rest_framework import viewsets
from accounts.models import UserProfile
from .models import Course
from .api.serializer import CoursesSerializer
from qualification.api.permissions import AdminOnlyForCrud
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
class CoursesView(viewsets.ModelViewSet):
    queryset = Course.objects.all()
    serializer_class = CoursesSerializer
    permission_classes = [AdminOnlyForCrud]

    @action(detail=False, methods=["GET"])
    def all(self, request):
        course = Course.objects.filter(user_profile__appuser = request.user)
        serializer = self.get_serializer(course, many=True)
        return Response({"data":serializer.data, })
    
    @action(detail=False, methods=["POST"])
    def add(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user_profile=[UserProfile.objects.get(appuser=request.user)])
        return Response({"message":f"""course has been added to the user {request.user}""","data":serializer.data})
    
    @action(detail=False, methods=["GET","PATCH"], url_path="edit(?:/(?P<pk>[^/.]+))?")
    def edit(self, request, pk=None):
        try:
            course = Course.objects.get(pk=pk,user_profile__appuser=request.user)
        except Course.DoesNotExist:
            return Response({"error":"the course does not found."}, status=status.HTTP_404_NOT_FOUND)
        if request.method == "GET":
            serializer = self.get_serializer(course)
            return Response({'data':serializer.data})
        serializer = self.get_serializer(course, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"message":f"""course has been updated to the user {request.user}""","data":serializer.data})
    
    @action(detail=False, methods=["GET","DELETE"], url_path="delete(?:/(?P<pk>[^/.]+))?")
    def delete(self, request, pk=None):
        try:
            course = Course.objects.get(pk=pk,user_profile__appuser=request.user)
        except Course.DoesNotExist:
            return Response({"error":"the course does not found."}, status=status.HTTP_404_NOT_FOUND)
        if request.method == "GET":
            serializer = self.get_serializer(course)
            return Response({'data':serializer.data})
        course.delete()
        return Response({"message":"qualification has been deleted"},status=status.HTTP_200_OK)