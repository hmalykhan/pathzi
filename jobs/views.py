import operator
from functools import reduce

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from django.db.models import Q
from django.db.models.functions import Greatest, Lower
from django.contrib.postgres.search import TrigramSimilarity

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



