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
        if not self.request.user.is_authenticated:
            return Apprenticeship.objects.none()

        profile = UserProfile.objects.filter(appuser=self.request.user).first()
        if not profile:
            return Apprenticeship.objects.none()

        # ---------- category filter (case-insensitive) ----------
        categories = profile.category or []
        if isinstance(categories, str):
            categories = [categories]
        categories = [c.strip().lower() for c in categories if c and c.strip()]
        if not categories:
            return Apprenticeship.objects.none()

        base_qs = Apprenticeship.objects.annotate(cat_l=Lower("category")).filter(cat_l__in=categories)

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
            return Apprenticeship.objects.none()   # strict: must match location

        # ---------- 1) strict partial match (preferred) ----------
        qs = base_qs.annotate(loc_l=Lower("location_summary")).exclude(loc_l__isnull=True).exclude(loc_l="")

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
            return Apprenticeship.objects.none()

        similarities = [TrigramSimilarity("loc_l", t) for t in terms]

        if len(similarities) == 1:
            qs = qs.annotate(sim=similarities[0])
        else:
            qs = qs.annotate(sim=Greatest(*similarities))

        # raise threshold a bit so it doesn't match too broadly
        return qs.filter(sim__gte=0.3).order_by("-sim")