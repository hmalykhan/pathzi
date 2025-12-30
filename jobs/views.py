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





# import inspect
# from functools import update_wrapper

# from asgiref.sync import sync_to_async
# from django.utils.decorators import classonlymethod
# from django.views.decorators.csrf import csrf_exempt

# from rest_framework import viewsets, status
# from rest_framework.decorators import action
# from rest_framework.response import Response

# from accounts.models import UserProfile
# from jobs.models import Job, UserSavedJob
# from jobs.api.serializers import JobsSerializer
# from jobs.api.permissions import JobPermission
# from django.db.models import Q
# from django.db.models.functions import Greatest, Lower
# from django.contrib.postgres.search import TrigramSimilarity


# class JobsView(viewsets.ModelViewSet):
#     permission_classes = [JobPermission]
#     queryset = Job.objects.all()
#     serializer_class = JobsSerializer

#     # --------- IMPORTANT: async-capable viewset plumbing ----------
#     @classonlymethod
#     def as_view(cls, actions=None, **initkwargs):
#         # same validations DRF does
#         cls.name = None
#         cls.description = None
#         cls.suffix = None
#         cls.detail = None
#         cls.basename = None

#         if not actions:
#             raise TypeError(
#                 "The `actions` argument must be provided when calling `.as_view()` "
#                 "on a ViewSet. For example `.as_view({'get': 'list'})`"
#             )

#         for key in initkwargs:
#             if key in cls.http_method_names:
#                 raise TypeError(
#                     f"You tried to pass in the {key} method name as a keyword argument "
#                     f"to {cls.__name__}(). Don't do that."
#                 )
#             if not hasattr(cls, key):
#                 raise TypeError(f"{cls.__name__}() received an invalid keyword {key!r}")

#         if "name" in initkwargs and "suffix" in initkwargs:
#             raise TypeError(
#                 f"{cls.__name__}() received both `name` and `suffix`, which are mutually exclusive."
#             )

#         async def view(request, *args, **kwargs):
#             self = cls(**initkwargs)

#             # DRF viewset binding
#             self.action_map = actions
#             for method, action_name in actions.items():
#                 handler = getattr(self, action_name)
#                 setattr(self, method, handler)

#             if hasattr(self, "get") and not hasattr(self, "head"):
#                 self.head = self.get

#             self.request = request
#             self.args = args
#             self.kwargs = kwargs

#             return await self.dispatch(request, *args, **kwargs)

#         update_wrapper(view, cls, updated=())
#         update_wrapper(view, cls.dispatch, assigned=())
#         view.cls = cls
#         view.initkwargs = initkwargs
#         view.actions = actions
#         return csrf_exempt(view)

#     async def dispatch(self, request, *args, **kwargs):
#         # async version of DRF APIView.dispatch
#         self.args = args
#         self.kwargs = kwargs

#         request = await sync_to_async(self.initialize_request, thread_sensitive=True)(
#             request, *args, **kwargs
#         )
#         self.request = request
#         self.headers = self.default_response_headers

#         try:
#             await sync_to_async(self.initial, thread_sensitive=True)(request, *args, **kwargs)

#             if request.method.lower() in self.http_method_names:
#                 handler = getattr(self, request.method.lower(), self.http_method_not_allowed)
#             else:
#                 handler = self.http_method_not_allowed

#             if inspect.iscoroutinefunction(handler):
#                 response = await handler(request, *args, **kwargs)
#             else:
#                 response = await sync_to_async(handler, thread_sensitive=True)(request, *args, **kwargs)

#         except Exception as exc:
#             response = await sync_to_async(self.handle_exception, thread_sensitive=True)(exc)

#         response = await sync_to_async(self.finalize_response, thread_sensitive=True)(
#             request, response, *args, **kwargs
#         )
#         self.response = response
#         return response

#     # --------- your code (same logic), now async actions ----------
#     async def _profile(self, request):
#         profile, _ = await sync_to_async(
#             UserProfile.objects.get_or_create,
#             thread_sensitive=True,
#         )(
#             appuser=request.user,
#             defaults={"age": 0},
#         )
#         return profile

#     @action(detail=True, methods=["POST", "GET"])
#     async def save(self, request, pk=None):
#         job = await sync_to_async(self.get_object, thread_sensitive=True)()

#         if request.method == "GET":
#             data = await sync_to_async(lambda: self.get_serializer(job).data, thread_sensitive=True)()
#             return Response(data)

#         user = await self._profile(request)
#         await sync_to_async(UserSavedJob.objects.get_or_create, thread_sensitive=True)(
#             user_profile=user, job_id=job.job_id
#         )

#         data = await sync_to_async(lambda: self.get_serializer(job).data, thread_sensitive=True)()
#         return Response(data, status=status.HTTP_200_OK)

#     @action(detail=False, methods=["GET"])
#     async def my(self, request):
#         user = await self._profile(request)

#         saved_ids = await sync_to_async(
#             lambda: list(
#                 UserSavedJob.objects.filter(user_profile=user).values_list("job_id", flat=True)
#             ),
#             thread_sensitive=True,
#         )()

#         data = await sync_to_async(
#             lambda: self.get_serializer(Job.objects.filter(job_id__in=saved_ids), many=True).data,
#             thread_sensitive=True,
#         )()
#         return Response(data, status=status.HTTP_200_OK)

#     @action(detail=True, methods=["POST", "GET"])
#     async def unsave(self, request, pk=None):
#         job = await sync_to_async(self.get_object, thread_sensitive=True)()

#         if request.method == "GET":
#             data = await sync_to_async(lambda: self.get_serializer(job).data, thread_sensitive=True)()
#             return Response(data)

#         user = await self._profile(request)
#         deleted, _ = await sync_to_async(
#             lambda: UserSavedJob.objects.filter(user_profile=user, job_id=job.job_id).delete(),
#             thread_sensitive=True,
#         )()

#         if deleted:
#             return Response({"message": "Job unsaved."}, status=status.HTTP_200_OK)

#         return Response({"error": "Job was not saved."}, status=status.HTTP_404_NOT_FOUND)

#     # --------- keep your original get_queryset unchanged ----------
#     def get_queryset(self):
#         if not self.request.user.is_authenticated:
#             return Job.objects.none()

#         profile = UserProfile.objects.filter(appuser=self.request.user).first()
#         if not profile:
#             return Job.objects.none()

#         categories = profile.category or []
#         if isinstance(categories, str):
#             categories = [categories]
#         categories = [c.strip().lower() for c in categories if c and c.strip()]
#         if not categories:
#             return Job.objects.none()

#         base_qs = Job.objects.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

#         raw_terms = []
#         if profile.city:
#             raw_terms.append(profile.city.strip().lower())
#         if profile.zip_code:
#             raw_terms.append(profile.zip_code.strip().lower())
#         if profile.address:
#             raw_terms.append(profile.address.strip().lower())

#         raw_terms = list({t for t in raw_terms if t})
#         if not raw_terms:
#             return Job.objects.none()

#         qs = base_qs.annotate(loc_l=Lower("location")).exclude(loc_l__isnull=True).exclude(loc_l="")

#         contains_q = Q()
#         for t in raw_terms:
#             contains_q |= Q(loc_l__icontains=t)

#         strict_qs = qs.filter(contains_q)
#         if strict_qs.exists():
#             return strict_qs

#         terms = []
#         for text in raw_terms:
#             for tok in text.replace(",", " ").split():
#                 tok = tok.strip()
#                 if len(tok) >= 3:
#                     terms.append(tok)
#         terms = list(dict.fromkeys(terms))
#         if not terms:
#             return Job.objects.none()

#         similarities = [TrigramSimilarity("loc_l", t) for t in terms]

#         if len(similarities) == 1:
#             qs = qs.annotate(sim=similarities[0])
#         else:
#             qs = qs.annotate(sim=Greatest(*similarities))

#         return qs.filter(sim__gte=0.3).order_by("-sim")

