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

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Job.objects.none()

        profile = UserProfile.objects.filter(appuser=self.request.user).first()
        if not profile:
            return Job.objects.none()

        # ---------- category filter (case-insensitive) ----------
        categories = profile.category or []
        if isinstance(categories, str):
            categories = [categories]
        categories = [c.strip().lower() for c in categories if c and c.strip()]
        if not categories:
            return Job.objects.none()

        base_qs = Job.objects.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

        # ---------- location terms ----------
        raw_terms = []
        if profile.city:
            raw_terms.append(profile.city.strip())
        if profile.zip_code:
            raw_terms.append(profile.zip_code.strip())
        if profile.address:
            raw_terms.append(profile.address.strip())

        raw_terms = list({t for t in raw_terms if t})
        if not raw_terms:
            return Job.objects.none()  # strict: must match location

        # ---------- 1) strict partial match (preferred) ----------
        qs = base_qs.exclude(location__isnull=True).exclude(location="")

        contains_q = Q()
        for t in raw_terms:
            contains_q |= Q(location__icontains=t)

        strict_qs = qs.filter(contains_q)
        if strict_qs.exists():
            return strict_qs

        # ---------- 2) fuzzy match fallback (misspellings) ----------
        # tokenise for fuzzy; keep >=3 chars
        terms = []
        for text in raw_terms:
            for tok in text.replace(",", " ").split():
                tok = tok.strip()
                if len(tok) >= 3:
                    terms.append(tok)

        terms = list(dict.fromkeys(terms))
        if not terms:
            return Job.objects.none()

        # Use trigram operator (index-friendly) to prefilter candidates
        trigram_q = reduce(operator.or_, [Q(location__trigram_similar=t) for t in terms], Q())
        qs = qs.filter(trigram_q)

        similarities = [TrigramSimilarity("location", t) for t in terms]
        if len(similarities) == 1:
            qs = qs.annotate(sim=similarities[0])
        else:
            qs = qs.annotate(sim=Greatest(*similarities))

        # threshold + rank
        return qs.filter(sim__gte=0.3).order_by("-sim")


