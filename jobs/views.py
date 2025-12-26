# from rest_framework import viewsets
# from .models import Job
# from .api.serializer import JobsSerializer
# from rest_framework.permissions import IsAuthenticated
# from accounts.models import UserProfile
# from rest_framework import status
# from rest_framework.response import Response
# from rest_framework.decorators import action
# from .api.permissions import JobPermission
# from django.shortcuts import get_object_or_404

# class JobsView(viewsets.ModelViewSet):
#     permission_classes = [JobPermission]
#     queryset = Job.objects.all()
#     serializer_class = JobsSerializer
    
#     @action(detail=True, methods=["POST","GET"])
#     def save(self, request, pk=None):
#         job = self.get_object()
#         serializer = self.get_serializer(job)
#         if request.method == "GET":
#             return Response(serializer.data)
#         user = get_object_or_404(UserProfile, appuser=self.request.user)
#         job.user_profile.add(user)
#         return Response(serializer.data)

#     @action(detail=False, methods=["GET"])
#     def my(self, request):
#         jobs = Job.objects.filter(user_profile__appuser=request.user)
#         serializer = self.get_serializer(jobs, many=True)
#         return Response(serializer.data)
    
#     @action(detail=True, methods=["POST","GET"])
#     def unsave(self, request, pk=None):
#         job = self.get_object()
#         if request.method == "GET":
#             serializer = self.get_serializer(job)
#             return Response(serializer.data)
#         user = get_object_or_404(UserProfile, appuser=self.request.user)
#         if job.user_profile.filter(pk = user.pk).exists():
#             job.user_profile.remove(user)
#             return Response({'message':'the user has been delete'})
#         return Response({'error':'no user found in this job.'},status=status.HTTP_404_NOT_FOUND)
    
#     # def get_queryset(self):
#     #     if self.request.user.is_staff:
#     #         return Job.objects.all()
#     #     if self.request.user.is_authenticated:
#     #         return Job.objects.filter(user_profile__appuser=self.request.user)
#     #     return Job.objects.none()

#     # def perform_create(self, serializer):
#     #     if not self.request.user.is_staff:
#     #         serializer.save(user_profile=[UserProfile.objects.get(appuser=self.request.user)]) 
#     #     else:
#     #         serializer.save()



# jobs/views.py
# jobs/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import UserProfile
from jobs.models import Job, UserSavedJob
from jobs.api.serializers import JobsSerializer
from jobs.api.permissions import JobPermission


class JobsView(viewsets.ModelViewSet):
    permission_classes = [JobPermission]
    queryset = Job.objects.all()
    serializer_class = JobsSerializer

    def _profile(self, request):
        profile, _ = UserProfile.objects.get_or_create(
            appuser=request.user,
            defaults={"age": 0},
        )
        return profile

    @action(detail=True, methods=["POST", "GET"])
    def save(self, request, pk=None):
        job = self.get_object()
        if request.method == "GET":
            return Response(self.get_serializer(job).data)

        user = self._profile(request)
        UserSavedJob.objects.get_or_create(user_profile=user, job_id=job.job_id)
        return Response(self.get_serializer(job).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"])
    def my(self, request):
        user = self._profile(request)
        saved_ids = UserSavedJob.objects.filter(user_profile=user).values_list("job_id", flat=True)
        jobs = Job.objects.filter(job_id__in=saved_ids)
        return Response(self.get_serializer(jobs, many=True).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST", "GET"])
    def unsave(self, request, pk=None):
        job = self.get_object()
        if request.method == "GET":
            return Response(self.get_serializer(job).data)

        user = self._profile(request)
        deleted, _ = UserSavedJob.objects.filter(user_profile=user, job_id=job.job_id).delete()

        if deleted:
            return Response({"message": "Job unsaved."}, status=status.HTTP_200_OK)

        return Response({"error": "Job was not saved."}, status=status.HTTP_404_NOT_FOUND)
    
    # def get_queryset(self):
    #      if self.request.user.is_staff:
    #          return Job.objects.all()
    #      if self.request.user.is_authenticated:
    #         #  return Job.objects.filter(user_profile__appuser=self.request.user)
    #         user = UserProfile.objects.get(user=self.request.user)
    #         return Job.objects.filter(user_profile__appuser=self.request.user)
    #      return Job.objects.none()

