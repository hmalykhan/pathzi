# apprenticeship/serializers.py
from rest_framework import serializers
from apprenticeship.models import Apprenticeship, UserSavedApprenticeship
from accounts.models import UserProfile


class UserProfileNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = "__all__"


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        if request and request.user.is_authenticated and not request.user.is_staff:
            self.fields.pop("user_profile_id", None)

        # ✅ Make scraped fields read-only (only relation is writable)
        for name, field in self.fields.items():
            if name not in ("user_profile", "user_profile_id"):
                field.read_only = True

    def get_user_profile(self, obj):
        ids = UserSavedApprenticeship.objects.filter(
            vacancy_ref=obj.vacancy_ref
        ).values_list("user_profile_id", flat=True)

        profiles = UserProfile.objects.filter(id__in=ids)
        return UserProfileNestedSerializer(
            profiles, many=True, context=self.context
        ).data

    def _sync_links(self, apprenticeship_obj, profiles):
        new_ids = {p.id for p in profiles}
        existing_ids = set(
            UserSavedApprenticeship.objects.filter(
                vacancy_ref=apprenticeship_obj.vacancy_ref
            ).values_list("user_profile_id", flat=True)
        )

        # remove links not in new set
        UserSavedApprenticeship.objects.filter(
            vacancy_ref=apprenticeship_obj.vacancy_ref,
            user_profile_id__in=(existing_ids - new_ids),
        ).delete()

        # add new links
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
