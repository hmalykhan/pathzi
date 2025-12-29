

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import UserProfile
from jobs.models import Job, UserSavedJob
from jobs.api.serializers import JobsSerializer
from jobs.api.permissions import JobPermission
from django.db.models import Q
from django.db.models.functions import Greatest, Lower
from django.contrib.postgres.search import TrigramSimilarity


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
            raw_terms.append(profile.city.strip().lower())
        if profile.zip_code:
            raw_terms.append(profile.zip_code.strip().lower())
        if profile.address:
            raw_terms.append(profile.address.strip().lower())

        raw_terms = list({t for t in raw_terms if t})
        if not raw_terms:
            return Job.objects.none()   # strict: must match location

        # ---------- 1) strict partial match (preferred) ----------
        qs = base_qs.annotate(loc_l=Lower("location")).exclude(loc_l__isnull=True).exclude(loc_l="")

        contains_q = Q()
        for t in raw_terms:
            contains_q |= Q(loc_l__icontains=t)

        strict_qs = qs.filter(contains_q)
        if strict_qs.exists():
            return strict_qs

        # ---------- 2) fuzzy match fallback (misspellings) ----------
        # tokenise (optional) for fuzzy; keep >=3 chars
        terms = []
        for text in raw_terms:
            for tok in text.replace(",", " ").split():
                tok = tok.strip()
                if len(tok) >= 3:
                    terms.append(tok)
        terms = list(dict.fromkeys(terms))
        if not terms:
            return Job.objects.none()

        similarities = [TrigramSimilarity("loc_l", t) for t in terms]

        if len(similarities) == 1:
            qs = qs.annotate(sim=similarities[0])
        else:
            qs = qs.annotate(sim=Greatest(*similarities))

        # raise threshold a bit so it doesn't match too broadly
        return qs.filter(sim__gte=0.3).order_by("-sim")






# import logging

# from asgiref.sync import sync_to_async
# from django.contrib.postgres.search import TrigramSimilarity
# from django.db.models import Q
# from django.db.models.functions import Greatest, Lower
# from rest_framework import status
# from rest_framework.decorators import action
# from rest_framework.exceptions import NotFound
# from rest_framework.response import Response

# from adrf.viewsets import ViewSet  # pip install adrf

# from accounts.models import UserProfile
# from jobs.api.permissions import JobPermission
# from jobs.api.serializers import JobsSerializer
# from jobs.models import Job, UserSavedJob

# logger = logging.getLogger(__name__)


# class JobsView(ViewSet):
#     """
#     Async ViewSet (requires `adrf`).

#     Notes:
#     - Serializer access is synchronous (`serializer.data`), so we run it inside `sync_to_async`.
#     - `get_or_create()` is also synchronous/transactional, so we run it inside `sync_to_async`.
#     """

#     permission_classes = [JobPermission]
#     serializer_class = JobsSerializer

#     # -------------------------
#     # Small async helpers
#     # -------------------------
#     from asgiref.sync import sync_to_async

#     async def _serialize(self, instance=None, many=False, data=None, partial=False):
#         # IMPORTANT: don't pass data=... unless you're validating input
#         if data is None:
#             serializer = self.serializer_class(instance=instance, many=many)
#             payload = await sync_to_async(lambda: serializer.data, thread_sensitive=True)()
#             return serializer, payload

#         serializer = self.serializer_class(instance=instance, data=data, many=many, partial=partial)
#         await sync_to_async(serializer.is_valid, thread_sensitive=True)(raise_exception=True)
#         payload = await sync_to_async(lambda: serializer.data, thread_sensitive=True)()
#         return serializer, payload


#     async def _profile(self, request) -> UserProfile:
#         """
#         Ensure a UserProfile exists for the request user.
#         Uses sync_to_async because get_or_create is sync/transactional.
#         """
#         if not request.user or not request.user.is_authenticated:
#             raise NotFound("User not authenticated.")

#         profile, created = await sync_to_async(
#             UserProfile.objects.get_or_create,
#             thread_sensitive=True,
#         )(appuser=request.user, defaults={"age": 0})

#         if created:
#             logger.info("Created user profile", extra={"user_id": request.user.id})
#         return profile

#     async def _get_job_any_or_404(self, pk) -> Job:
#         job = await Job.objects.filter(pk=pk).afirst()
#         if not job:
#             raise NotFound("Job not found.")
#         return job

#     async def _build_feed_jobs(self, request):
#         """
#         Replicates your original get_queryset() logic, but fully async.
#         Returns a list[Job] (already evaluated).
#         """
#         if not request.user or not request.user.is_authenticated:
#             logger.debug("Anonymous user: returning no jobs")
#             return []

#         profile = await UserProfile.objects.filter(appuser=request.user).afirst()
#         if not profile:
#             logger.warning("No profile found: returning no jobs", extra={"user_id": request.user.id})
#             return []

#         # ---------- category filter (case-insensitive) ----------
#         categories = profile.category or []
#         if isinstance(categories, str):
#             categories = [categories]
#         categories = [c.strip().lower() for c in categories if c and c.strip()]
#         if not categories:
#             logger.info("No categories on profile: returning no jobs", extra={"user_id": request.user.id})
#             return []

#         base_qs = Job.objects.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

#         # ---------- location terms ----------
#         raw_terms = []
#         if profile.city:
#             raw_terms.append(profile.city.strip().lower())
#         if profile.zip_code:
#             raw_terms.append(profile.zip_code.strip().lower())
#         if profile.address:
#             raw_terms.append(profile.address.strip().lower())

#         raw_terms = list({t for t in raw_terms if t})
#         if not raw_terms:
#             logger.info(
#                 "No location terms on profile: returning no jobs (strict mode)",
#                 extra={"user_id": request.user.id},
#             )
#             return []  # strict: must match location

#         # ---------- 1) strict partial match (preferred) ----------
#         qs = (
#             base_qs.annotate(loc_l=Lower("location"))
#             .exclude(loc_l__isnull=True)
#             .exclude(loc_l="")
#         )

#         contains_q = Q()
#         for t in raw_terms:
#             contains_q |= Q(loc_l__icontains=t)

#         strict_qs = qs.filter(contains_q)
#         if await strict_qs.aexists():
#             logger.debug(
#                 "Strict match hit",
#                 extra={"user_id": request.user.id, "terms": raw_terms, "categories": categories},
#             )
#             return [job async for job in strict_qs]

#         # ---------- 2) fuzzy match fallback (misspellings) ----------
#         terms = []
#         for text in raw_terms:
#             for tok in text.replace(",", " ").split():
#                 tok = tok.strip()
#                 if len(tok) >= 3:
#                     terms.append(tok)
#         terms = list(dict.fromkeys(terms))
#         if not terms:
#             logger.info("No fuzzy tokens extracted: returning no jobs", extra={"user_id": request.user.id})
#             return []

#         similarities = [TrigramSimilarity("loc_l", t) for t in terms]
#         if len(similarities) == 1:
#             qs = qs.annotate(sim=similarities[0])
#         else:
#             qs = qs.annotate(sim=Greatest(*similarities))

#         fuzzy_qs = qs.filter(sim__gte=0.3).order_by("-sim")

#         logger.debug(
#             "Fuzzy match used",
#             extra={"user_id": request.user.id, "tokens": terms, "categories": categories},
#         )
#         return [job async for job in fuzzy_qs]

#     async def _get_job_from_feed_or_404(self, request, pk) -> Job:
#         # Try strict/fuzzy feed logic, but restricted to this pk
#         jobs = await self._build_feed_jobs(request)
#         for j in jobs:
#             if str(j.pk) == str(pk):
#                 return j
#         raise NotFound("Job not found in your feed.")

#     # -------------------------
#     # Standard ViewSet actions
#     # -------------------------
#     async def list(self, request):
#         try:
#             jobs = await self._build_feed_jobs(request)
#             _, payload = await self._serialize(instance=jobs, many=True)
#             return Response(payload, status=status.HTTP_200_OK)
#         except Exception:
#             logger.exception("Failed to list jobs", extra={"user_id": getattr(request.user, "id", None)})
#             raise

#     async def retrieve(self, request, pk=None):
#         try:
#             job = await self._get_job_from_feed_or_404(request, pk)
#             _, payload = await self._serialize(instance=job, many=False)
#             return Response(payload, status=status.HTTP_200_OK)
#         except Exception:
#             logger.exception(
#                 "Failed to retrieve job",
#                 extra={"user_id": getattr(request.user, "id", None), "pk": pk},
#             )
#             raise

#     async def create(self, request):
#         # Keep CRUD compatibility (since you originally used ModelViewSet)
#         logger.warning("Create called on JobsView", extra={"user_id": getattr(request.user, "id", None)})
#         serializer, payload = await self._serialize(data=request.data, many=False)
#         job = await sync_to_async(serializer.save, thread_sensitive=True)()
#         _, out = await self._serialize(instance=job, many=False)
#         return Response(out, status=status.HTTP_201_CREATED)

#     async def update(self, request, pk=None):
#         job = await self._get_job_any_or_404(pk)
#         serializer, _ = await self._serialize(instance=job, data=request.data, partial=False)
#         job = await sync_to_async(serializer.save, thread_sensitive=True)()
#         _, out = await self._serialize(instance=job, many=False)
#         return Response(out, status=status.HTTP_200_OK)

#     async def partial_update(self, request, pk=None):
#         job = await self._get_job_any_or_404(pk)
#         serializer, _ = await self._serialize(instance=job, data=request.data, partial=True)
#         job = await sync_to_async(serializer.save, thread_sensitive=True)()
#         _, out = await self._serialize(instance=job, many=False)
#         return Response(out, status=status.HTTP_200_OK)

#     async def destroy(self, request, pk=None):
#         job = await self._get_job_any_or_404(pk)
#         await sync_to_async(job.delete, thread_sensitive=True)()
#         return Response(status=status.HTTP_204_NO_CONTENT)

#     # -------------------------
#     # Custom actions
#     # -------------------------
#     @action(detail=True, methods=["POST", "GET"])
#     async def save(self, request, pk=None):
#         job = await self._get_job_from_feed_or_404(request, pk)

#         if request.method == "GET":
#             _, payload = await self._serialize(instance=job, many=False)
#             return Response(payload, status=status.HTTP_200_OK)

#         user_profile = await self._profile(request)

#         # get_or_create is sync/transactional -> thread
#         _, created = await sync_to_async(
#             UserSavedJob.objects.get_or_create,
#             thread_sensitive=True,
#         )(user_profile=user_profile, job_id=job.job_id)

#         logger.info(
#             "Job saved",
#             extra={"user_id": request.user.id, "job_id": job.job_id, "created": created},
#         )

#         _, payload = await self._serialize(instance=job, many=False)
#         return Response(payload, status=status.HTTP_200_OK)

#     @action(detail=False, methods=["GET"])
#     async def my(self, request):
#         user_profile = await self._profile(request)

#         saved_ids = [
#             jid
#             async for jid in UserSavedJob.objects.filter(user_profile=user_profile)
#             .values_list("job_id", flat=True)
#         ]

#         jobs = [j async for j in Job.objects.filter(job_id__in=saved_ids)]

#         logger.debug(
#             "Fetched saved jobs",
#             extra={"user_id": request.user.id, "count": len(jobs)},
#         )

#         _, payload = await self._serialize(instance=jobs, many=True)
#         return Response(payload, status=status.HTTP_200_OK)

#     @action(detail=True, methods=["POST", "GET"])
#     async def unsave(self, request, pk=None):
#         job = await self._get_job_from_feed_or_404(request, pk)

#         if request.method == "GET":
#             _, payload = await self._serialize(instance=job, many=False)
#             return Response(payload, status=status.HTTP_200_OK)

#         user_profile = await self._profile(request)

#         # delete is query-causing; Django supports async variants, but keep it safe in thread
#         deleted_count, _ = await sync_to_async(
#             UserSavedJob.objects.filter(user_profile=user_profile, job_id=job.job_id).delete,
#             thread_sensitive=True,
#         )()

#         if deleted_count:
#             logger.info("Job unsaved", extra={"user_id": request.user.id, "job_id": job.job_id})
#             return Response({"message": "Job unsaved."}, status=status.HTTP_200_OK)

#         logger.warning("Unsave requested but job wasn't saved", extra={"user_id": request.user.id, "job_id": job.job_id})
#         return Response({"error": "Job was not saved."}, status=status.HTTP_404_NOT_FOUND)
