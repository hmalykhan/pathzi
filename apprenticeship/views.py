# apprenticeship/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import UserProfile
from apprenticeship.models import Apprenticeship, UserSavedApprenticeship
from apprenticeship.api.serializers import ApprenticeshipSerializer
from apprenticeship.api.permissions import ApprenticeshipPermission
from django.db.models import Q
from django.db.models.functions import Greatest, Lower
from django.contrib.postgres.search import TrigramSimilarity
import re
from django.db.models import Q, Value, TextField, IntegerField, Case, When
from django.db.models.functions import Lower, Replace, Trim, Coalesce, Cast, Greatest
from django.contrib.postgres.search import TrigramSimilarity


class ApprenticeshipView(viewsets.ModelViewSet):
    queryset = Apprenticeship.objects.all()
    serializer_class = ApprenticeshipSerializer
    permission_classes = [ApprenticeshipPermission]

    def _profile(self, request):
        # avoids UserProfile.DoesNotExist
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
        return Response(
            self.get_serializer(apprenticeship).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["GET"])
    def my(self, request):
        user = self._profile(request)
        saved_refs = UserSavedApprenticeship.objects.filter(
            user_profile=user
        ).values_list("vacancy_ref", flat=True)

        apprenticeships = Apprenticeship.objects.filter(vacancy_ref__in=saved_refs)
        return Response(
            self.get_serializer(apprenticeships, many=True).data,
            status=status.HTTP_200_OK,
        )

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
            return Response(
                {"message": "Apprenticeship unsaved."},
                status=status.HTTP_200_OK,
            )

        return Response(
            {"error": "Apprenticeship was not saved."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    def get_queryset(self):
        print("\n========== Apprenticeship.get_queryset() START ==========")

        user = getattr(self.request, "user", None)
        print("User:", user, "| authenticated:", bool(user and user.is_authenticated))
        if not user or not user.is_authenticated:
            print("-> Not authenticated. Returning none().")
            return Apprenticeship.objects.none()

        profile = UserProfile.objects.filter(appuser=user).first()
        print("Profile found:", bool(profile))
        if not profile:
            print("-> No profile. Returning none().")
            return Apprenticeship.objects.none()

        # ---------- category filter (case-insensitive) ----------
        categories = profile.category or []
        if isinstance(categories, str):
            categories = [categories]
        categories = [c.strip().lower() for c in categories if c and c.strip()]
        print("Categories (normalized):", categories)

        if not categories:
            print("-> No categories. Returning none().")
            return Apprenticeship.objects.none()

        base_qs = Apprenticeship.objects.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)
        print("base_qs count:", base_qs.count())

        # ---------- profile raw terms (same as your current logic) ----------
        raw_terms = []
        if getattr(profile, "city", None):
            raw_terms.append(profile.city.strip().lower())
        if getattr(profile, "zip_code", None):
            raw_terms.append(profile.zip_code.strip().lower())
        if getattr(profile, "address", None):
            raw_terms.append(profile.address.strip().lower())

        raw_terms = list({t for t in raw_terms if t})
        print("raw_terms:", raw_terms)

        if not raw_terms:
            print("-> No location terms. Returning none().")
            return Apprenticeship.objects.none()

        # Convert raw_terms into "words" (alnum only)
        profile_text = " ".join(raw_terms)
        words = [w for w in re.split(r"[^a-z0-9]+", profile_text) if w]
        words = list(dict.fromkeys(words))  # dedupe keep order
        print("Profile words:", words, "| count:", len(words))

        # ---------- normalize Apprenticeship.location_summary into loc_n ----------
        # Fix mixed types by forcing TextField output
        empty_text = Value("", output_field=TextField())

        loc = Coalesce(
            Cast("location_summary", output_field=TextField()),
            empty_text,
            output_field=TextField()
        )
        loc = Lower(Trim(loc))

        # Remove spaces + common separators so matches like "newyork10001" work
        for ch in [" ", "\n", "\t", "\r", ",", ".", "-", "/", "#"]:
            loc = Replace(
                loc,
                Value(ch, output_field=TextField()),
                empty_text,
                output_field=TextField(),
            )

        loc = Cast(loc, output_field=TextField())

        qs = base_qs.annotate(loc_n=loc).exclude(loc_n="")
        print("qs count after normalize:", qs.count())
        print("Sample location_summary:", list(qs.values_list("location_summary", flat=True)[:3]))
        print("Sample loc_n:", list(qs.values_list("loc_n", flat=True)[:3]))

        # ---------- 1) strict: consecutive-3 merged words match ----------
        if len(words) >= 3:
            merged3 = []
            for i in range(len(words) - 2):
                merged3.append(words[i] + words[i + 1] + words[i + 2])
            merged3 = list(dict.fromkeys(merged3))
            print("Consecutive-3 merged chunks:", merged3)

            trigram_q = Q()
            for m in merged3:
                c = qs.filter(loc_n__contains=m).count()
                print(f"Chunk '{m}' -> matches:", c)
                trigram_q |= Q(loc_n__contains=m)

            strict_qs = qs.filter(trigram_q)
            print("Strict result count:", strict_qs.count())

            if strict_qs.exists():
                print("-> Returning strict consecutive-3 results")
                print("========== Apprenticeship.get_queryset() END ==========\n")
                return strict_qs

            print("-> No strict consecutive-3 matches, fallback to word-count...")

        # ---------- 2) fallback: require at least 2 words match (prevents york->yorkshire alone) ----------
        if not words:
            print("-> No words after parsing. Returning none().")
            return Apprenticeship.objects.none()

        threshold = 2 if len(words) >= 2 else 1
        print("Fallback word-match threshold:", threshold)

        match_expr = Value(0, output_field=IntegerField())
        for w in words:
            match_expr += Case(
                When(loc_n__contains=w, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )

        qs2 = qs.annotate(match_count=match_expr)

        for w in words:
            c = qs2.filter(loc_n__contains=w).count()
            print(f"Word '{w}' -> matches:", c)

        word_match_qs = qs2.filter(match_count__gte=threshold).order_by("-match_count")
        print("Word-match result count:", word_match_qs.count())

        if word_match_qs.exists():
            print("-> Returning word-match results")
            print("Sample results:", list(word_match_qs.values("location_summary", "match_count")[:5]))
            print("========== Apprenticeship.get_queryset() END ==========\n")
            return word_match_qs

        print("-> No word-match results, fallback to trigram similarity...")

        # ---------- 3) fuzzy fallback: Trigram similarity (misspellings) ----------
        # Use tokens >= 3 chars
        terms = [w for w in words if len(w) >= 3]
        terms = list(dict.fromkeys(terms))
        print("Trigram terms:", terms)

        if not terms:
            print("-> No trigram terms. Returning none().")
            print("========== Apprenticeship.get_queryset() END ==========\n")
            return Apprenticeship.objects.none()

        similarities = [TrigramSimilarity("loc_n", t) for t in terms]
        if len(similarities) == 1:
            qs3 = qs.annotate(sim=similarities[0])
        else:
            qs3 = qs.annotate(sim=Greatest(*similarities))

        result = qs3.filter(sim__gte=0.3).order_by("-sim")
        print("Trigram result count:", result.count())
        print("Sample trigram results:", list(result.values("location_summary", "sim")[:5]))

        print("========== Apprenticeship.get_queryset() END ==========\n")
        return result