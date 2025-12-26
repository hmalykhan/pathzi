# from rest_framework import viewsets
# from accounts.models import UserProfile
# from .models import Course
# from .api.serializer import CoursesSerializer
# from .api.permissions import CoursePermission
# from rest_framework.decorators import action
# from rest_framework.response import Response
# from rest_framework import status
# from django.shortcuts import get_object_or_404
# class CoursesView(viewsets.ModelViewSet):
#     queryset = Course.objects.all()
#     serializer_class = CoursesSerializer
#     permission_classes = [CoursePermission]

#     @action(detail=True, methods=["POST","GET"])
#     def save(self, request, pk=None):
#         course = self.get_object()
#         serializer = self.get_serializer(course)
#         if request.method == "GET":
#             return Response(serializer.data)
#         user = get_object_or_404(UserProfile, appuser=self.request.user)
#         course.user_profile.add(user)
#         return Response(serializer.data)

#     @action(detail=False, methods=["GET"])
#     def my(self, request):
#         course = Course.objects.filter(user_profile__appuser=request.user)
#         serializer = self.get_serializer(course, many=True)
#         return Response(serializer.data)
    
#     @action(detail=True, methods=["POST","GET"])
#     def unsave(self, request, pk=None):
#         course = self.get_object()
#         if request.method == "GET":
#             serializer = self.get_serializer(course)
#             return Response(serializer.data)
#         user = get_object_or_404(UserProfile, appuser=self.request.user)
#         if course.user_profile.filter(pk = user.pk).exists():
#             course.user_profile.remove(user)
#             return Response({'message':'the user has been delete'})
#         return Response({'error':'no user found in this job.'},status=status.HTTP_404_NOT_FOUND)

#     # @action(detail=False, methods=["GET"])
#     # def all(self, request):
#     #     course = Course.objects.filter(user_profile__appuser = request.user)
#     #     serializer = self.get_serializer(course, many=True)
#     #     return Response({"data":serializer.data, })
    
#     # @action(detail=False, methods=["POST"])
#     # def add(self, request):
#     #     serializer = self.get_serializer(data=request.data)
#     #     serializer.is_valid(raise_exception=True)
#     #     serializer.save(user_profile=[UserProfile.objects.get(appuser=request.user)])
#     #     return Response({"message":f"""course has been added to the user {request.user}""","data":serializer.data})
    
#     # @action(detail=False, methods=["GET","PATCH"], url_path="edit(?:/(?P<pk>[^/.]+))?")
#     # def edit(self, request, pk=None):
#     #     try:
#     #         course = Course.objects.get(pk=pk,user_profile__appuser=request.user)
#     #     except Course.DoesNotExist:
#     #         return Response({"error":"the course does not found."}, status=status.HTTP_404_NOT_FOUND)
#     #     if request.method == "GET":
#     #         serializer = self.get_serializer(course)
#     #         return Response({'data':serializer.data})
#     #     serializer = self.get_serializer(course, data=request.data, partial=True)
#     #     serializer.is_valid(raise_exception=True)
#     #     serializer.save()
#     #     return Response({"message":f"""course has been updated to the user {request.user}""","data":serializer.data})
    
#     # @action(detail=False, methods=["GET","DELETE"], url_path="delete(?:/(?P<pk>[^/.]+))?")
#     # def delete(self, request, pk=None):
#     #     try:
#     #         course = Course.objects.get(pk=pk,user_profile__appuser=request.user)
#     #     except Course.DoesNotExist:
#     #         return Response({"error":"the course does not found."}, status=status.HTTP_404_NOT_FOUND)
#     #     if request.method == "GET":
#     #         serializer = self.get_serializer(course)
#     #         return Response({'data':serializer.data})
#     #     course.delete()
#     #     return Response({"message":"qualification has been deleted"},status=status.HTTP_200_OK)





from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from accounts.models import UserProfile
from .models import Course, UserSavedCourse
from .api.serializer import CoursesSerializer
from .api.permissions import CoursePermission


class CoursesView(viewsets.ModelViewSet):
    queryset = Course.objects.all()
    serializer_class = CoursesSerializer
    permission_classes = [CoursePermission]

    @action(detail=True, methods=["POST", "GET"])
    def save(self, request, pk=None):
        course = self.get_object()

        # Same as before: GET returns course data
        if request.method == "GET":
            serializer = self.get_serializer(course)
            return Response(serializer.data)

        # POST: create the link in join table
        user = get_object_or_404(UserProfile, appuser=request.user)

        UserSavedCourse.objects.get_or_create(
            user_profile=user,
            course_id=course.course_id,  # IMPORTANT: link by scraper UUID
        )

        serializer = self.get_serializer(course)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"])
    def my(self, request):
        # Same as before: return courses saved by current user
        user, _ = UserProfile.objects.get_or_create(appuser=request.user, defaults={"age": 0})

        saved_course_ids = UserSavedCourse.objects.filter(
            user_profile=user
        ).values_list("course_id", flat=True)

        courses = Course.objects.filter(course_id__in=saved_course_ids)
        serializer = self.get_serializer(courses, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST", "GET"])
    def unsave(self, request, pk=None):
        course = self.get_object()

        # Same as before: GET returns course data
        if request.method == "GET":
            serializer = self.get_serializer(course)
            return Response(serializer.data)

        user, _ = UserProfile.objects.get_or_create(appuser=request.user, defaults={"age": 0})

        deleted_count, _ = UserSavedCourse.objects.filter(
            user_profile=user,
            course_id=course.course_id,
        ).delete()

        if deleted_count > 0:
            return Response({"message": "the user has been delete"}, status=status.HTTP_200_OK)

        return Response(
            {"error": "no user found in this course."},
            status=status.HTTP_404_NOT_FOUND,
        )
