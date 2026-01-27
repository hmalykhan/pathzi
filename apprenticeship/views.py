import re

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import UserProfile
from apprenticeship.models import Apprenticeship, UserSavedApprenticeship
from apprenticeship.api.serializers import ApprenticeshipSerializer
from apprenticeship.api.permissions import ApprenticeshipPermission

from django.db.models import Q, Value, TextField, IntegerField, Case, When
from django.db.models.functions import Lower, Replace, Trim, Coalesce, Cast, Greatest
from django.contrib.postgres.search import TrigramSimilarity


class ApprenticeshipView(viewsets.ModelViewSet):
    queryset = Apprenticeship.objects.all()
    serializer_class = ApprenticeshipSerializer
    permission_classes = [ApprenticeshipPermission]

    def _profile(self, request):
        profile, _ = UserProfile.objects.get_or_create(
            appuser=request.user,
            defaults={"age": 0},
        )
        return profile

    @action(detail=True, methods=["POST", "GET"])
    def save(self, request, pk=None):
        apprenticeship = self.get_object()
        if request.method == "GET":
            return Response(self.get_serializer(apprenticeship).data)

        user = self._profile(request)
        UserSavedApprenticeship.objects.get_or_create(
            user_profile=user,
            vacancy_ref=apprenticeship.vacancy_ref,
        )
        return Response(self.get_serializer(apprenticeship).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["GET"])
    def my(self, request):
        user = self._profile(request)
        saved_refs = UserSavedApprenticeship.objects.filter(
            user_profile=user
        ).values_list("vacancy_ref", flat=True)

        apprenticeships = Apprenticeship.objects.filter(vacancy_ref__in=saved_refs)
        return Response(self.get_serializer(apprenticeships, many=True).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST", "GET"])
    def unsave(self, request, pk=None):
        apprenticeship = self.get_object()
        if request.method == "GET":
            return Response(self.get_serializer(apprenticeship).data)

        user = self._profile(request)
        deleted, _ = UserSavedApprenticeship.objects.filter(
            user_profile=user,
            vacancy_ref=apprenticeship.vacancy_ref,
        ).delete()

        if deleted:
            return Response({"message": "Apprenticeship unsaved."}, status=status.HTTP_200_OK)

        return Response({"error": "Apprenticeship was not saved."}, status=status.HTTP_404_NOT_FOUND)

    # def get_queryset(self):
    #     user = getattr(self.request, "user", None)
    #     if not user or not user.is_authenticated:
    #         return Apprenticeship.objects.none()

    #     profile = UserProfile.objects.filter(appuser=user).first()
    #     if not profile:
    #         return Apprenticeship.objects.none()

    #     # ---------- category filter (case-insensitive) ----------
    #     categories = profile.category or []
    #     if isinstance(categories, str):
    #         categories = [categories]
    #     categories = [c.strip().lower() for c in categories if c and c.strip()]
    #     if not categories:
    #         return Apprenticeship.objects.none()

    #     base_qs = Apprenticeship.objects.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

    #     # ---------- location raw terms ----------
    #     raw_terms = []
    #     if getattr(profile, "city", None):
    #         raw_terms.append(profile.city.strip().lower())
    #     if getattr(profile, "zip_code", None):
    #         raw_terms.append(profile.zip_code.strip().lower())
    #     if getattr(profile, "address", None):
    #         raw_terms.append(profile.address.strip().lower())

    #     raw_terms = list({t for t in raw_terms if t})
    #     if not raw_terms:
    #         return Apprenticeship.objects.none()

    #     # Convert to alnum words
    #     profile_text = " ".join(raw_terms)
    #     words = [w for w in re.split(r"[^a-z0-9]+", profile_text) if w]
    #     words = list(dict.fromkeys(words))
    #     if not words:
    #         return Apprenticeship.objects.none()

    #     # ---------- normalize location_summary into loc_n ----------
    #     empty_text = Value("", output_field=TextField())

    #     loc = Coalesce(
    #         Cast("location_summary", output_field=TextField()),
    #         empty_text,
    #         output_field=TextField(),
    #     )
    #     loc = Lower(Trim(loc))

    #     for ch in [" ", "\n", "\t", "\r", ",", ".", "-", "/", "#"]:
    #         loc = Replace(
    #             loc,
    #             Value(ch, output_field=TextField()),
    #             empty_text,
    #             output_field=TextField(),
    #         )

    #     loc = Cast(loc, output_field=TextField())

    #     qs = base_qs.annotate(loc_n=loc).exclude(loc_n="")

    #     # ---------- 1) strict: consecutive-3 merged word chunks ----------
    #     if len(words) >= 3:
    #         merged3 = []
    #         for i in range(len(words) - 2):
    #             merged3.append(words[i] + words[i + 1] + words[i + 2])
    #         merged3 = list(dict.fromkeys(merged3))

    #         strict_q = Q()
    #         for m in merged3:
    #             strict_q |= Q(loc_n__contains=m)

    #         strict_qs = qs.filter(strict_q)
    #         if strict_qs.exists():
    #             return strict_qs

    #     # ---------- 2) fallback: require >=2 word matches (or 1 if only 1 word) ----------
    #     threshold = 2 if len(words) >= 2 else 1

    #     match_expr = Value(0, output_field=IntegerField())
    #     for w in words:
    #         match_expr += Case(
    #             When(loc_n__contains=w, then=Value(1)),
    #             default=Value(0),
    #             output_field=IntegerField(),
    #         )

    #     qs2 = qs.annotate(match_count=match_expr)
    #     word_match_qs = qs2.filter(match_count__gte=threshold).order_by("-match_count")
    #     if word_match_qs.exists():
    #         return word_match_qs

    #     # ---------- 3) fuzzy fallback: trigram similarity ----------
    #     terms = [w for w in words if len(w) >= 3]
    #     terms = list(dict.fromkeys(terms))
    #     if not terms:
    #         return Apprenticeship.objects.none()

    #     similarities = [TrigramSimilarity("loc_n", t) for t in terms]
    #     if len(similarities) == 1:
    #         qs3 = qs.annotate(sim=similarities[0])
    #     else:
    #         qs3 = qs.annotate(sim=Greatest(*similarities))

    #     return qs3.filter(sim__gte=0.3).order_by("-sim")

    def get_queryset(self):
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return Apprenticeship.objects.none()

        profile = UserProfile.objects.filter(appuser=user).first()
        if not profile:
            return Apprenticeship.objects.none()

        # ------------------- 1) subcategory filter -------------------
        # Tries profile.subcategory first; falls back to profile.category (your old behavior)
        subcats = getattr(profile, "subcategory", None) or getattr(profile, "subcategories", None) or profile.category or []
        if isinstance(subcats, str):
            subcats = [subcats]
        subcats = [s.strip().lower() for s in subcats if s and str(s).strip()]
        if not subcats:
            return Apprenticeship.objects.none()

        base_qs = (
            Apprenticeship.objects
            .annotate(sub_l=Lower("subcategory"))
            .filter(sub_l__in=subcats)
        )

        # ------------------- 2) strict city match -------------------
        profile_city = getattr(profile, "city", None)
        if not profile_city or not str(profile_city).strip():
            return Apprenticeship.objects.none()

        # normalize profile city: lowercase + remove spaces/separators
        pc = str(profile_city).strip().lower()
        pc = re.sub(r"[^a-z0-9]+", "", pc)  # removes spaces + punctuation

        empty_text = Value("", output_field=TextField())

        # normalize DB city the same way (lowercase + remove spaces/separators)
        db_city = Coalesce(Cast("city", output_field=TextField()), empty_text, output_field=TextField())
        db_city = Lower(Trim(db_city))

        # remove common separators (rough equivalent of regex, but DB-safe)
        for ch in [" ", "\n", "\t", "\r", ",", ".", "-", "/", "#"]:
            db_city = Replace(db_city, Value(ch, output_field=TextField()), empty_text, output_field=TextField())

        qs = base_qs.annotate(city_n=db_city)

        # exact match after normalization
        return qs.filter(city_n=pc)
