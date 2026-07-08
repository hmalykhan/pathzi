# from django.db import transaction
# from django.db.models import QuerySet
# from rest_framework import serializers

# from careers.models import Career, UserSavedCareer
# from accounts.models import UserProfile


# class UserProfileNestedSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = UserProfile
#         fields = "__all__"


# class CareerListSerializer(serializers.ModelSerializer):
#     category = serializers.CharField(source="sub_type", read_only=True)
#     subcategory = serializers.CharField(source="jobname", read_only=True)
#     class Meta:
#         model = Career
#         fields = (
#             "id",
#             "career_type",
#             # "sub_type",
#             "category",
#             # "jobname",
#             "subcategory",
#             "image_url",
#             "job_slug",
#             "job_url",
#             "job_description",
#             "salary",
#             "hours",
#             "timings",
#             "how_to_become",
#             "college",
#             "college_entry_req",
#             "apprenticeship_entry_req",
#             "apprenticeship",
#             "scraped_at",
#         )
#         read_only_fields = fields


# class CareerDetailSerializer(serializers.ModelSerializer):
#     category = serializers.CharField(source="sub_type", read_only=True)
#     subcategory = serializers.CharField(source="jobname", read_only=True)
#     user_profile = serializers.SerializerMethodField(read_only=True)

#     user_profile_id = serializers.PrimaryKeyRelatedField(
#         many=True,
#         required=False,
#         write_only=True,
#         queryset=UserProfile.objects.all(),
#     )

#     class Meta:
#         model = Career
#         fields = (
#             "id",
#             "user_profile_id",
#             "user_profile",
#             "career_type",
#             # "sub_type",
#             "category",
#             # "jobname",
#             "image_url",
#             "subcategory",
#             "job_slug",
#             "job_url",
#             "job_description",
#             "salary",
#             "hours",
#             "timings",
#             "how_to_become",
#             "college",
#             "college_entry_req",
#             "apprenticeship_entry_req",
#             "apprenticeship",
#             "scraped_at",
#         )

#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)

#         request = self.context.get("request")
#         if request and request.user.is_authenticated and not request.user.is_staff:
#             self.fields.pop("user_profile_id", None)

#         for name, field in self.fields.items():
#             if name not in ("user_profile", "user_profile_id"):
#                 field.read_only = True

#         self._profiles_by_career_id = None
#         instance = getattr(self, "instance", None)
#         if instance is None:
#             return

#         if isinstance(instance, (list, tuple, QuerySet)):
#             career_ids = [obj.id for obj in instance]
#             if career_ids:
#                 links = UserSavedCareer.objects.filter(career_id__in=career_ids).values(
#                     "career_id", "user_profile_id"
#                 )

#                 prof_ids_by_career = {}
#                 all_profile_ids = set()
#                 for row in links:
#                     cid = row["career_id"]
#                     pid = row["user_profile_id"]
#                     prof_ids_by_career.setdefault(cid, set()).add(pid)
#                     all_profile_ids.add(pid)

#                 profiles = UserProfile.objects.filter(id__in=all_profile_ids)
#                 profiles_by_id = {p.id: p for p in profiles}

#                 self._profiles_by_career_id = {
#                     cid: [profiles_by_id[pid] for pid in pids if pid in profiles_by_id]
#                     for cid, pids in prof_ids_by_career.items()
#                 }

#     def get_user_profile(self, obj):
#         if self._profiles_by_career_id is not None:
#             profiles = self._profiles_by_career_id.get(obj.id, [])
#             return UserProfileNestedSerializer(profiles, many=True, context=self.context).data

#         profiles = UserProfile.objects.filter(career_links__career_id=obj.id).distinct()
#         return UserProfileNestedSerializer(profiles, many=True, context=self.context).data

#     def _sync_links(self, career_obj, profiles):
#         new_ids = {p.id for p in profiles}
#         existing_ids = set(
#             UserSavedCareer.objects.filter(career_id=career_obj.id).values_list(
#                 "user_profile_id", flat=True
#             )
#         )

#         UserSavedCareer.objects.filter(
#             career_id=career_obj.id,
#             user_profile_id__in=(existing_ids - new_ids),
#         ).delete()

#         UserSavedCareer.objects.bulk_create(
#             [
#                 UserSavedCareer(career_id=career_obj.id, user_profile_id=pid)
#                 for pid in (new_ids - existing_ids)
#             ],
#             ignore_conflicts=True,
#         )

#     @transaction.atomic
#     def update(self, instance, validated_data):
#         profiles = validated_data.pop("user_profile_id", None)
#         if profiles is not None:
#             self._sync_links(instance, profiles)
#         return instance




from django.db import transaction
from django.db.models import QuerySet
from rest_framework import serializers

from careers.models import Career, UserSavedCareer
from accounts.models import UserProfile


class UserProfileNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = "__all__"

class CareerFilterSerializer(serializers.ModelSerializer):
        category = serializers.CharField(source="sub_type", read_only=True)
        subcategory = serializers.CharField(source="jobname", read_only=True)
        class Meta:
            model = Career
            fields = [
                "id",
                "category",
                "subcategory",
                "job_description",
                "dg_image_url",
                "salary"
            ]


def _empty_my_report():
    return {"report_status": False, "report": {}, "generated_at": None}


class CareerListSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source="sub_type", read_only=True)
    subcategory = serializers.CharField(source="jobname", read_only=True)

    # ✅ user+career oriented report
    my_report = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Career
        fields = (
            "id",
            "career_type",
            "category",
            "subcategory",
            "image_url",
            "dg_image_url",
            "job_slug",
            "job_url",
            "job_description",
            "salary",
            "hours",
            "timings",
            "how_to_become",
            "college",
            "college_entry_req",
            "apprenticeship_entry_req",
            "apprenticeship",
            "scraped_at",
            "my_report",  # ✅ added
        )
        read_only_fields = fields

    def get_my_report(self, obj):
        """
        Uses report_map injected by the view to avoid N+1 queries.
        report_map: {career_id: UserSavedCareer instance} for current user's profile.
        """
        report_map = self.context.get("report_map") or {}
        link = report_map.get(obj.id)
        if not link:
            return _empty_my_report()

        return {
            "report_status": bool(getattr(link, "report_status", False)),
            "report": getattr(link, "report", None) or {},
            "generated_at": getattr(link, "generated_at", None),
        }


class CareerDetailSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source="sub_type", read_only=True)
    subcategory = serializers.CharField(source="jobname", read_only=True)

    ADMIN_WRITABLE_FIELDS = {
        "category", "subcategory"
        # "user_profile_id",  # if you still want this
    }

    # existing admin feature, this line will show the ids of all users who are having the career in their save list. it has also field in the fields. and also the moethod below named as get_user_profile.
    # user_profile = serializers.SerializerMethodField(read_only=True) 

    user_profile_id = serializers.PrimaryKeyRelatedField(
        many=True,
        required=False,
        write_only=True,
        queryset=UserProfile.objects.all(),
    )


    # ✅ user+career oriented report
    my_report = serializers.SerializerMethodField(read_only=True)
    is_saved = serializers.SerializerMethodField()
    is_explored = serializers.SerializerMethodField()

    class Meta:
        model = Career
        fields = (
            "id",
            "user_profile_id",
            # "user_profile",
            "career_type",
            "category",
            "image_url",
            "dg_image_url",
            "subcategory",
            "job_slug",
            "job_url",
            "job_description",
            "salary",
            "hours",
            "timings",
            "how_to_become",
            "college",
            "college_entry_req",
            "apprenticeship_entry_req",
            "apprenticeship",
            "scraped_at",
            "my_report",  # ✅ added
            "is_saved",
            "is_explored",
        )

    # new
    # def __init__(self, *args, **kwargs):
    #     super().__init__(*args, **kwargs)

    #     request = self.context.get("request")

    #     if request and request.user.is_authenticated and not request.user.is_staff:
    #         self.fields.pop("user_profile_id", None)

    #     # ✅ default: everything read-only except these
    #     for name, field in self.fields.items():
    #         if name not in ("user_profile", "user_profile_id", "my_report"):
    #             field.read_only = True

    #     # ✅ staff: allow only ADMIN_WRITABLE_FIELDS
    #     if request and request.user.is_authenticated and request.user.is_staff:
    #         for name in self.ADMIN_WRITABLE_FIELDS:
    #             if name in self.fields:
    #                 self.fields[name].read_only = False

    #     # ---- existing prefetch behavior for user_profile (unchanged) ----
    #     self._profiles_by_career_id = None
    #     instance = getattr(self, "instance", None)
    #     if instance is None:
    #         return

    #     if isinstance(instance, (list, tuple, QuerySet)):
    #         career_ids = [obj.id for obj in instance]
    #         if career_ids:
    #             links = UserSavedCareer.objects.filter(career_id__in=career_ids).values(
    #                 "career_id", "user_profile_id"
    #             )

    #             prof_ids_by_career = {}
    #             all_profile_ids = set()
    #             for row in links:
    #                 cid = row["career_id"]
    #                 pid = row["user_profile_id"]
    #                 prof_ids_by_career.setdefault(cid, set()).add(pid)
    #                 all_profile_ids.add(pid)

    #             profiles = UserProfile.objects.filter(id__in=all_profile_ids)
    #             profiles_by_id = {p.id: p for p in profiles}

    #             self._profiles_by_career_id = {
    #                 cid: [profiles_by_id[pid] for pid in pids if pid in profiles_by_id]
    #                 for cid, pids in prof_ids_by_career.items()
    #             }

    # original
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        if request and request.user.is_authenticated and not request.user.is_staff:
            self.fields.pop("user_profile_id", None)

        for name, field in self.fields.items():
            if name not in ("user_profile", "user_profile_id", "my_report"):
                field.read_only = True

        # ---- existing prefetch behavior for user_profile ----
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

    def get_my_report(self, obj):
        """
        Same as list: returns current user's report object for this career.
        """
        report_map = self.context.get("report_map") or {}
        link = report_map.get(obj.id)
        if not link:
            return _empty_my_report()

        return {
            "report_status": bool(getattr(link, "report_status", False)),
            "report": getattr(link, "report", None) or {},
            "generated_at": getattr(link, "generated_at", None),
        }

    # ---- existing admin sync feature (unchanged) ----
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

    # old
    @transaction.atomic
    def update(self, instance, validated_data):
        profiles = validated_data.pop("user_profile_id", None)
        if profiles is not None:
            self._sync_links(instance, profiles)
        return instance
    
    def get_is_saved(self, obj):
        saved_map = self.context.get("saved_map") or {}
        return obj.id in saved_map


    def get_is_explored(self, obj):
        explored_map = self.context.get("explored_map") or {}
        return obj.id in explored_map

    # new
    # @transaction.atomic
    # def update(self, instance, validated_data):
    #     profiles = validated_data.pop("user_profile_id", None)

    #     # ✅ update model fields (only admin-writable ones can reach here)
    #     for attr, value in validated_data.items():
    #         setattr(instance, attr, value)

    #     if validated_data:
    #         instance.save(update_fields=list(validated_data.keys()))

    #     # ✅ keep existing link sync behavior if enabled
    #     if profiles is not None:
    #         self._sync_links(instance, profiles)

    #     return instance



    from rest_framework import serializers


class CareerInteractionItemSerializer(serializers.Serializer):
    career_id = serializers.IntegerField(required=True)
    saved = serializers.BooleanField(required=False)
    explored = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if "saved" not in attrs and "explored" not in attrs:
            raise serializers.ValidationError(
                "At least one of saved or explored is required."
            )
        return attrs


class BulkCareerInteractionSerializer(serializers.Serializer):
    items = CareerInteractionItemSerializer(many=True)

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("items cannot be empty.")

        if len(items) > 100:
            raise serializers.ValidationError(
                "You can update at most 100 career interactions at once."
            )

        # Final state wins per career_id.
        merged = {}

        for item in items:
            career_id = item["career_id"]

            if career_id not in merged:
                merged[career_id] = {
                    "career_id": career_id,
                }

            if "saved" in item:
                merged[career_id]["saved"] = item["saved"]

            if "explored" in item:
                merged[career_id]["explored"] = item["explored"]

        return list(merged.values())



    
