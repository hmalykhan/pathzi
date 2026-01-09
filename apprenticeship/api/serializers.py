from collections import defaultdict

from rest_framework import serializers
from apprenticeship.models import Apprenticeship, UserSavedApprenticeship
from accounts.models import UserProfile


class UserProfileNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = "__all__"


class ApprenticeshipListSerializer(serializers.ListSerializer):
    """
    ✅ Avoid N+1 queries for user_profile by preloading links + profiles once.
    vacancy_ref -> [serialized user profiles...]
    """
    def to_representation(self, data):
        items = list(data)
        if not items:
            return []

        refs = [obj.vacancy_ref for obj in items if getattr(obj, "vacancy_ref", None)]
        refs = list(dict.fromkeys(refs))
        if not refs:
            self.child._profiles_by_ref = {}
            return super().to_representation(items)

        links = list(
            UserSavedApprenticeship.objects
            .filter(vacancy_ref__in=refs)
            .values_list("vacancy_ref", "user_profile_id")
        )

        ref_to_profile_ids = defaultdict(set)
        profile_ids = set()
        for ref, pid in links:
            ref_to_profile_ids[ref].add(pid)
            profile_ids.add(pid)

        if profile_ids:
            profiles_qs = UserProfile.objects.filter(id__in=profile_ids)
            serialized_profiles = UserProfileNestedSerializer(
                profiles_qs, many=True, context=self.context
            ).data
            profiles_by_id = {p["id"]: p for p in serialized_profiles}
        else:
            profiles_by_id = {}

        profiles_by_ref = {}
        for ref, pids in ref_to_profile_ids.items():
            profiles_by_ref[ref] = [profiles_by_id[pid] for pid in pids if pid in profiles_by_id]

        self.child._profiles_by_ref = profiles_by_ref
        return super().to_representation(items)


class ApprenticeshipSerializer(serializers.ModelSerializer):
    user_profile = serializers.SerializerMethodField(read_only=True)

    user_profile_id = serializers.PrimaryKeyRelatedField(
        many=True,
        required=False,
        write_only=True,
        queryset=UserProfile.objects.all(),
    )

    class Meta:
        model = Apprenticeship
        fields = "__all__"
        list_serializer_class = ApprenticeshipListSerializer  # ✅ enable bulk optimization

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        if request and request.user.is_authenticated and not request.user.is_staff:
            self.fields.pop("user_profile_id", None)

        # ✅ scraped fields read-only
        for name, field in self.fields.items():
            if name not in ("user_profile", "user_profile_id"):
                field.read_only = True

    def get_user_profile(self, obj):
        # ✅ fast path for list
        profiles_map = getattr(self, "_profiles_by_ref", None)
        if profiles_map is not None:
            return profiles_map.get(obj.vacancy_ref, [])

        # fallback for retrieve
        ids = UserSavedApprenticeship.objects.filter(
            vacancy_ref=obj.vacancy_ref
        ).values_list("user_profile_id", flat=True)
        profiles = UserProfile.objects.filter(id__in=ids)
        return UserProfileNestedSerializer(profiles, many=True, context=self.context).data

    def _sync_links(self, apprenticeship_obj, profiles):
        new_ids = {p.id for p in profiles}
        existing_ids = set(
            UserSavedApprenticeship.objects.filter(
                vacancy_ref=apprenticeship_obj.vacancy_ref
            ).values_list("user_profile_id", flat=True)
        )

        UserSavedApprenticeship.objects.filter(
            vacancy_ref=apprenticeship_obj.vacancy_ref,
            user_profile_id__in=(existing_ids - new_ids),
        ).delete()

        UserSavedApprenticeship.objects.bulk_create(
            [
                UserSavedApprenticeship(
                    vacancy_ref=apprenticeship_obj.vacancy_ref,
                    user_profile_id=pid,
                )
                for pid in (new_ids - existing_ids)
            ],
            ignore_conflicts=True,
        )

    def update(self, instance, validated_data):
        profiles = validated_data.pop("user_profile_id", None)
        if profiles is not None:
            self._sync_links(instance, profiles)
        return instance
