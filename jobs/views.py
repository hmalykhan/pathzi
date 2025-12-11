from rest_framework import viewsets
from .models import Job
from .api.serializer import JobsSerializer
from rest_framework.permissions import IsAuthenticated
from accounts.models import UserProfile
from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import action
from .api.permissions import JobPermission

class JobsView(viewsets.ModelViewSet):
    permission_classes = [JobPermission]
    queryset = Job.objects.all()
    serializer_class = JobsSerializer
    
    def create(self, request, pk=None,*args, **kwargs):
        if request.user.is_staff:
            return super().create(request, *args, **kwargs)
        job = Job.objects.get(pk = pk)
        if not job:
            return Response({"message":"no job found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(data = job)
        serializer.is_valid(raise_exception=True)
        serializer.save(user_profile=[UserProfile.objects.get(appuser=self.request.user)])

    @action(detail=False, methods=["GET"])
    def my(self, request):
        jobs = Job.objects.filter(user_profile__appuser=request.user)
        if not jobs:
            return Response({"message":"no job found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(jobs, many=True)
        return Response(serializer.data)
    
    # def get_queryset(self):
    #     if self.request.user.is_staff:
    #         return Job.objects.all()
    #     if self.request.user.is_authenticated:
    #         return Job.objects.filter(user_profile__appuser=self.request.user)
    #     return Job.objects.none()

    # def perform_create(self, serializer):
    #     if not self.request.user.is_staff:
    #         serializer.save(user_profile=[UserProfile.objects.get(appuser=self.request.user)]) 
    #     else:
    #         serializer.save()