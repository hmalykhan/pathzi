from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from accounts.models import UserProfile
from .models import Course, UserSavedCourse
from .api.serializer import CoursesSerializer
from .api.permissions import CoursePermission
from django.contrib.postgres.search import TrigramSimilarity
import re
from django.db.models import Q, Value, TextField
from django.db.models.functions import Lower, Replace, Trim, Coalesce, Cast
from django.db.models import Case, When, Value, IntegerField, TextField


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
    
    def get_queryset(self):
        print("\n========== get_queryset() START ==========")

        user = getattr(self.request, "user", None)
        print("User:", user, "| authenticated:", bool(user and user.is_authenticated))
        if not user or not user.is_authenticated:
            print("-> Not authenticated. Returning none().")
            return Course.objects.none()

        profile = UserProfile.objects.filter(appuser=user).first()
        print("Profile found:", bool(profile))
        if not profile:
            print("-> No profile. Returning none().")
            return Course.objects.none()

        # ---------- category filter (case-insensitive) ----------
        categories = profile.category or []
        if isinstance(categories, str):
            categories = [categories]
        categories = [c.strip().lower() for c in categories if c and c.strip()]
        print("Categories (normalized):", categories)

        if not categories:
            print("-> No categories. Returning none().")
            return Course.objects.none()

        base_qs = Course.objects.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)
        print("base_qs count:", base_qs.count())

        # ---------- build words from country/city/zip ----------
        country = (getattr(profile, "country", None) or "").strip().lower()
        city = (getattr(profile, "city", None) or "").strip().lower()
        postal = (getattr(profile, "zip_code", None) or "").strip().lower()

        profile_text = " ".join([x for x in [country, city, postal] if x])
        print("Profile text (raw):", repr(profile_text))

        words = [w for w in re.split(r"[^a-z0-9]+", profile_text) if w]
        words = list(dict.fromkeys(words))  # dedupe keep order
        print("Words:", words, "| count:", len(words))

        if not words:
            print("-> No words, returning none().")
            return Course.objects.none()

        # If only 1 word exists, requiring 2 would always return empty
        # Choose threshold = min(2, len(words)) so it still works.
        THRESHOLD = 2 if len(words) >= 2 else 1
        print("Match threshold:", THRESHOLD)

        # ---------- normalize course address to loc_n ----------
        empty_text = Value("", output_field=TextField())
        addr = Coalesce(Cast("address", output_field=TextField()), empty_text, output_field=TextField())
        addr = Lower(Trim(addr))

        # remove spaces + common separators
        for ch in [" ", "\n", "\t", "\r", ",", ".", "-", "/", "#"]:
            addr = Replace(
                addr,
                Value(ch, output_field=TextField()),
                empty_text,
                output_field=TextField(),
            )
        addr = Cast(addr, output_field=TextField())

        qs = base_qs.annotate(loc_n=addr).exclude(loc_n="")
        print("qs count after normalize:", qs.count())
        print("Sample address:", list(qs.values_list("address", flat=True)[:5]))
        print("Sample loc_n:", list(qs.values_list("loc_n", flat=True)[:5]))

        # ---------- compute match_count = number of words found in loc_n ----------
        match_expr = Value(0, output_field=IntegerField())
        for w in words:
            # NOTE: loc_n has removed separators, words are alnum, so contains works
            match_expr += Case(
                When(loc_n__contains=w, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )

        qs = qs.annotate(match_count=match_expr)

        # logs per word
        for w in words:
            c = qs.filter(loc_n__contains=w).count()
            print(f"Word '{w}' -> matches:", c)

        result = qs.filter(match_count__gte=THRESHOLD).order_by("-match_count")
        print("Final result count:", result.count())
        print("Final sample (address, match_count):", list(result.values("address", "match_count")[:10]))

        print("========== get_queryset() END ==========\n")
        return result







# import inspect
# from functools import update_wrapper

# from asgiref.sync import sync_to_async
# from django.utils.decorators import classonlymethod
# from django.views.decorators.csrf import csrf_exempt
# from django.shortcuts import get_object_or_404

# from rest_framework import viewsets, status
# from rest_framework.decorators import action
# from rest_framework.response import Response

# from accounts.models import UserProfile
# from .models import Course, UserSavedCourse
# from .api.serializer import CoursesSerializer
# from .api.permissions import CoursePermission
# from django.db.models import Q
# from django.db.models.functions import Greatest, Lower
# from django.contrib.postgres.search import TrigramSimilarity


# class CoursesView(viewsets.ModelViewSet):
#     queryset = Course.objects.all()
#     serializer_class = CoursesSerializer
#     permission_classes = [CoursePermission]

#     # -----------------------------
#     # ✅ Async-capable DRF plumbing
#     # -----------------------------
#     @classonlymethod
#     def as_view(cls, actions=None, **initkwargs):
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

#         async def view(request, *args, **kwargs):
#             self = cls(**initkwargs)

#             # Bind methods like DRF does (get->list, post->create, etc.)
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
#         # Async version of DRF APIView.dispatch
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

#     # -----------------------------
#     # ✅ Your actions (async)
#     # -----------------------------
#     @action(detail=True, methods=["POST", "GET"])
#     async def save(self, request, pk=None):
#         course = await sync_to_async(self.get_object, thread_sensitive=True)()

#         # GET returns course data
#         if request.method == "GET":
#             data = await sync_to_async(
#                 lambda: self.get_serializer(course).data,
#                 thread_sensitive=True,
#             )()
#             return Response(data)

#         # POST: create the link in join table
#         user = await sync_to_async(
#             lambda: get_object_or_404(UserProfile, appuser=request.user),
#             thread_sensitive=True,
#         )()

#         await sync_to_async(UserSavedCourse.objects.get_or_create, thread_sensitive=True)(
#             user_profile=user,
#             course_id=course.course_id,  # IMPORTANT: link by scraper UUID
#         )

#         data = await sync_to_async(
#             lambda: self.get_serializer(course).data,
#             thread_sensitive=True,
#         )()
#         return Response(data, status=status.HTTP_200_OK)

#     @action(detail=False, methods=["GET"])
#     async def my(self, request):
#         user, _ = await sync_to_async(
#             UserProfile.objects.get_or_create,
#             thread_sensitive=True,
#         )(appuser=request.user, defaults={"age": 0})

#         saved_course_ids = await sync_to_async(
#             lambda: list(
#                 UserSavedCourse.objects.filter(user_profile=user)
#                 .values_list("course_id", flat=True)
#             ),
#             thread_sensitive=True,
#         )()

#         data = await sync_to_async(
#             lambda: self.get_serializer(
#                 Course.objects.filter(course_id__in=saved_course_ids),
#                 many=True
#             ).data,
#             thread_sensitive=True,
#         )()
#         return Response(data, status=status.HTTP_200_OK)

#     @action(detail=True, methods=["POST", "GET"])
#     async def unsave(self, request, pk=None):
#         course = await sync_to_async(self.get_object, thread_sensitive=True)()

#         # GET returns course data
#         if request.method == "GET":
#             data = await sync_to_async(
#                 lambda: self.get_serializer(course).data,
#                 thread_sensitive=True,
#             )()
#             return Response(data)

#         user, _ = await sync_to_async(
#             UserProfile.objects.get_or_create,
#             thread_sensitive=True,
#         )(appuser=request.user, defaults={"age": 0})

#         deleted_count, _ = await sync_to_async(
#             lambda: UserSavedCourse.objects.filter(
#                 user_profile=user,
#                 course_id=course.course_id,
#             ).delete(),
#             thread_sensitive=True,
#         )()

#         if deleted_count > 0:
#             return Response({"message": "the user has been delete"}, status=status.HTTP_200_OK)

#         return Response(
#             {"error": "no user found in this course."},
#             status=status.HTTP_404_NOT_FOUND,
#         )

#     # -----------------------------
#     # ✅ Keep your original get_queryset unchanged
#     # -----------------------------
#     def get_queryset(self):
#         if not self.request.user.is_authenticated:
#             return Course.objects.none()

#         profile = UserProfile.objects.filter(appuser=self.request.user).first()
#         if not profile:
#             return Course.objects.none()

#         # ---------- category filter (case-insensitive) ----------
#         categories = profile.category or []
#         if isinstance(categories, str):
#             categories = [categories]
#         categories = [c.strip().lower() for c in categories if c and c.strip()]
#         if not categories:
#             return Course.objects.none()

#         base_qs = Course.objects.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

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
#             return Course.objects.none()  # strict: must match location

#         # ---------- 1) strict partial match (preferred) ----------
#         qs = base_qs.annotate(loc_l=Lower("address")).exclude(loc_l__isnull=True).exclude(loc_l="")

#         contains_q = Q()
#         for t in raw_terms:
#             contains_q |= Q(loc_l__icontains=t)

#         strict_qs = qs.filter(contains_q)
#         if strict_qs.exists():
#             return strict_qs

#         # ---------- 2) fuzzy match fallback (index-friendly) ----------
#         # tokenise (optional) for fuzzy; keep >=3 chars
#         terms = []
#         for text in raw_terms:
#             for tok in text.replace(",", " ").split():
#                 tok = tok.strip()
#                 if len(tok) >= 3:
#                     terms.append(tok)
#         terms = list(dict.fromkeys(terms))
#         if not terms:
#             return Course.objects.none()

#         # ✅ First: fast trigram operator filter (uses pg_trgm threshold, index-friendly)
#         fuzzy_q = Q()
#         for t in terms:
#             fuzzy_q |= Q(loc_l__trigram_similar=t)

#         qs = qs.filter(fuzzy_q)

#         # ✅ Then: rank results (ranking can be slower but now runs on reduced set)
#         similarities = [TrigramSimilarity("loc_l", t) for t in terms]
#         if len(similarities) == 1:
#             qs = qs.annotate(sim=similarities[0])
#         else:
#             qs = qs.annotate(sim=Greatest(*similarities))

#         return qs.order_by("-sim")

