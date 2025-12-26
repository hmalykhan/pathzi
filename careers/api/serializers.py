# careers/serializers.py
from rest_framework import serializers
from careers.models import Career, UserSavedCareer
from accounts.models import UserProfile


class UserProfileNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = "__all__"


class CareersSerializer(serializers.ModelSerializer):
    user_profile = serializers.SerializerMethodField(read_only=True)

    user_profile_id = serializers.PrimaryKeyRelatedField(
        many=True,
        required=False,
        write_only=True,
        queryset=UserProfile.objects.all(),
    )

    class Meta:
        model = Career
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        if request and request.user.is_authenticated and not request.user.is_staff:
            self.fields.pop("user_profile_id", None)

        # ✅ make scraped fields read-only
        for name, field in self.fields.items():
            if name not in ("user_profile", "user_profile_id"):
                field.read_only = True

    def get_user_profile(self, obj):
        ids = UserSavedCareer.objects.filter(career_id=obj.id).values_list(
            "user_profile_id", flat=True
        )
        profiles = UserProfile.objects.filter(id__in=ids)
        return UserProfileNestedSerializer(profiles, many=True, context=self.context).data

    def _sync_links(self, career_obj, profiles):
        new_ids = {p.id for p in profiles}
        existing_ids = set(
            UserSavedCareer.objects.filter(career_id=career_obj.id).values_list(
                "user_profile_id", flat=True
            )
        )

        # remove old links
        UserSavedCareer.objects.filter(
            career_id=career_obj.id,
            user_profile_id__in=(existing_ids - new_ids),
        ).delete()

        # add new links
        UserSavedCareer.objects.bulk_create(
            [
                UserSavedCareer(career_id=career_obj.id, user_profile_id=pid)
                for pid in (new_ids - existing_ids)
            ],
            ignore_conflicts=True,
        )

    def update(self, instance, validated_data):
        profiles = validated_data.pop("user_profile_id", None)
        if profiles is not None:
            self._sync_links(instance, profiles)
        return instance
