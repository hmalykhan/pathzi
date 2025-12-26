# from rest_framework import serializers
# from jobs.models import Job
# from accounts.models import  UserProfile

# class UserProfileNestedSerializer(serializers.ModelSerializer): # Just to avoid the circular imports error, this is called the nested serializer.
#     class Meta:
#         model = UserProfile
#         fields = "__all__"

# class JobsSerializer(serializers.ModelSerializer):
#     user_profile = UserProfileNestedSerializer(many=True, read_only=True)
#     user_profile_id = serializers.PrimaryKeyRelatedField(many=True, write_only=True, queryset = UserProfile.objects.all(), source='user_profile')
#     class Meta:
#         model = Job
#         fields = "__all__"

#     def __init__(self,*args, **kwargs):
#         super().__init__(*args, **kwargs)
#         request = self.context.get('request', None)
#         if request and request.user.is_authenticated and not request.user.is_staff:
#             self.fields.pop('user_profile_id', None)





# jobs/serializers.py
# jobs/serializers.py
from rest_framework import serializers
from jobs.models import Job, UserSavedJob
from accounts.models import UserProfile


class UserProfileNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = "__all__"


class JobsSerializer(serializers.ModelSerializer):
    user_profile = serializers.SerializerMethodField(read_only=True)

    user_profile_id = serializers.PrimaryKeyRelatedField(
        many=True,
        required=False,
        write_only=True,
        queryset=UserProfile.objects.all(),
    )

    # ✅ Compatibility aliases (old API fields)
    job_name = serializers.CharField(source="title", read_only=True)
    status = serializers.CharField(source="last_scrape_status", read_only=True)
    duration = serializers.CharField(source="hours", read_only=True)

    class Meta:
        model = Job
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        if request and request.user.is_authenticated and not request.user.is_staff:
            self.fields.pop("user_profile_id", None)

        # ✅ prevent writing scraped fields
        for name, field in self.fields.items():
            if name not in ("user_profile", "user_profile_id"):
                field.read_only = True

    def get_user_profile(self, obj):
        ids = UserSavedJob.objects.filter(job_id=obj.job_id).values_list(
            "user_profile_id", flat=True
        )
        profiles = UserProfile.objects.filter(id__in=ids)
        return UserProfileNestedSerializer(profiles, many=True, context=self.context).data

    def _sync_links(self, job_obj, profiles):
        new_ids = {p.id for p in profiles}
        existing_ids = set(
            UserSavedJob.objects.filter(job_id=job_obj.job_id).values_list(
                "user_profile_id", flat=True
            )
        )

        UserSavedJob.objects.filter(
            job_id=job_obj.job_id,
            user_profile_id__in=(existing_ids - new_ids),
        ).delete()

        UserSavedJob.objects.bulk_create(
            [
                UserSavedJob(job_id=job_obj.job_id, user_profile_id=pid)
                for pid in (new_ids - existing_ids)
            ],
            ignore_conflicts=True,
        )

    def update(self, instance, validated_data):
        profiles = validated_data.pop("user_profile_id", None)
        if profiles is not None:
            self._sync_links(instance, profiles)
        return instance
