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
from django.db.models import QuerySet
from rest_framework import serializers

from jobs.models import Job, UserSavedJob
from accounts.models import UserProfile


class UserProfileNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = "__all__"


class JobsSerializer(serializers.ModelSerializer):
    # One field name for "what do I need to start", the same across
    # careers, courses, jobs and apprenticeships - the underlying column
    # is named differently on every table.
    entry_requirements = serializers.SerializerMethodField(read_only=True)


# add the field you want in admin wirtable fields to edit them.
    ADMIN_WRITABLE_FIELDS = {
        "city", "state", "zip_code", "latitude", "longitude", "category", "subcategory"
        # "user_profile_id",  # if you still want this
    }

    # ADMIN_WRITABLE_FIELDS = {
    # f.name for f in Job._meta.fields
    # if f.name not in {"id", "job_id"}
    # } | {"user_profile_id"}

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


    def get_entry_requirements(self, obj):
        for name in ['skills_youll_need', 'requirement_summery']:
            value = getattr(obj, name, None)
            if isinstance(value, (list, tuple)):
                value = ", ".join(str(v) for v in value if v)
            if isinstance(value, str):
                value = value.strip()
            if value:
                return value
        return None

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

        if request and request.user.is_authenticated and request.user.is_staff:
            for name in self.ADMIN_WRITABLE_FIELDS:
                if name in self.fields:
                    self.fields[name].read_only = False

        # ✅ PERF: avoid N+1 when serializer is used with many=True
        self._profiles_by_job_id = None
        instance = getattr(self, "instance", None)
        if instance is None:
            return

        if isinstance(instance, (list, tuple, QuerySet)):
            job_ids = [obj.job_id for obj in instance if getattr(obj, "job_id", None)]
            job_ids = list(dict.fromkeys(job_ids))
            if not job_ids:
                self._profiles_by_job_id = {}
                return

            links = UserSavedJob.objects.filter(job_id__in=job_ids).values(
                "job_id", "user_profile_id"
            )

            prof_ids_by_job = {}
            all_profile_ids = set()
            for row in links:
                jid = row["job_id"]
                pid = row["user_profile_id"]
                prof_ids_by_job.setdefault(jid, set()).add(pid)
                all_profile_ids.add(pid)

            profiles = UserProfile.objects.filter(id__in=all_profile_ids)
            profiles_by_id = {p.id: p for p in profiles}

            self._profiles_by_job_id = {
                jid: [profiles_by_id[pid] for pid in pids if pid in profiles_by_id]
                for jid, pids in prof_ids_by_job.items()
            }

    def _may_see_profiles(self):
        """
        Only staff may see who saved this item.

        This used to return every saver's full profile - home address,
        postcode, GPS position, apple_sub, account_uuid - to ANYONE,
        including users who were not signed in. Several of these users are
        under 18.

        An empty list rather than a removed key, so an app reading the
        field keeps working and simply sees nobody.
        """
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and user.is_staff)

    def get_user_profile(self, obj):
        if not self._may_see_profiles():
            return []

        # ✅ Use cache for list
        if self._profiles_by_job_id is not None:
            profiles = self._profiles_by_job_id.get(obj.job_id, [])
            return UserProfileNestedSerializer(
                profiles, many=True, context=self.context
            ).data

        # ✅ Fallback for single-object serialization
        ids = UserSavedJob.objects.filter(job_id=obj.job_id).values_list(
            "user_profile_id", flat=True
        )
        if not ids:
            return []

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

    # def update(self, instance, validated_data):
    #     print("VALIDATED:", validated_data)
    #     profiles = validated_data.pop("user_profile_id", None)
    #     if profiles is not None:
    #         self._sync_links(instance, profiles)
    #     return instance

    def update(self, instance, validated_data):
        profiles = validated_data.pop("user_profile_id", None)

        # ✅ update model fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if validated_data:
            instance.save(update_fields=list(validated_data.keys()))

        # ✅ update link table if provided
        if profiles is not None:
            self._sync_links(instance, profiles)

        return instance
