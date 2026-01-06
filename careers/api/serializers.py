from django.db import transaction
from django.db.models import QuerySet
from rest_framework import serializers

from careers.models import Career, UserSavedCareer
from accounts.models import UserProfile


class UserProfileNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = "__all__"


class CareerListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Career
        fields = (
            "id",
            "career_type",
            "sub_type",
            "job_slug",
            "job_url",
            "image_url",
            "jobname",
            "salary",
            "hours",
            "timings",
            "last_scrape_status",
            "last_checked_at",
        )
        read_only_fields = fields


class CareerDetailSerializer(serializers.ModelSerializer):
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

        for name, field in self.fields.items():
            if name not in ("user_profile", "user_profile_id"):
                field.read_only = True

        self._profiles_by_career_id = None
        instance = getattr(self, "instance", None)
        if instance is None:
            return

        if isinstance(instance, (list, tuple, QuerySet)):
            career_ids = [obj.id for obj in instance]
            if career_ids:
                links = UserSavedCareer.objects.filter(career_id__in=career_ids).values(
                    "career_id", "user_profile_id"
                )

                prof_ids_by_career = {}
                all_profile_ids = set()
                for row in links:
                    cid = row["career_id"]
                    pid = row["user_profile_id"]
                    prof_ids_by_career.setdefault(cid, set()).add(pid)
                    all_profile_ids.add(pid)

                profiles = UserProfile.objects.filter(id__in=all_profile_ids)
                profiles_by_id = {p.id: p for p in profiles}

                self._profiles_by_career_id = {
                    cid: [profiles_by_id[pid] for pid in pids if pid in profiles_by_id]
                    for cid, pids in prof_ids_by_career.items()
                }

    def get_user_profile(self, obj):
        if self._profiles_by_career_id is not None:
            profiles = self._profiles_by_career_id.get(obj.id, [])
            return UserProfileNestedSerializer(profiles, many=True, context=self.context).data

        profiles = UserProfile.objects.filter(career_links__career_id=obj.id).distinct()
        return UserProfileNestedSerializer(profiles, many=True, context=self.context).data

    def _sync_links(self, career_obj, profiles):
        new_ids = {p.id for p in profiles}
        existing_ids = set(
            UserSavedCareer.objects.filter(career_id=career_obj.id).values_list(
                "user_profile_id", flat=True
            )
        )

        UserSavedCareer.objects.filter(
            career_id=career_obj.id,
            user_profile_id__in=(existing_ids - new_ids),
        ).delete()

        UserSavedCareer.objects.bulk_create(
            [
                UserSavedCareer(career_id=career_obj.id, user_profile_id=pid)
                for pid in (new_ids - existing_ids)
            ],
            ignore_conflicts=True,
        )

    @transaction.atomic
    def update(self, instance, validated_data):
        profiles = validated_data.pop("user_profile_id", None)
        if profiles is not None:
            self._sync_links(instance, profiles)
        return instance
