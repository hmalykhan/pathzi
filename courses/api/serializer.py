# from rest_framework import serializers
# from courses.models import Course
# from accounts.models import UserProfile
# # from accounts.serializers import UserProfileSerializer

# class UserProfileNestedSerializer(serializers.ModelSerializer): # Just to avoid the circular imports error, this is called the nested serializer.
#     class Meta:
#         model = UserProfile
#         fields = "__all__"

# class CoursesSerializer(serializers.ModelSerializer):
#     user_profile = UserProfileNestedSerializer( many=True, read_only=True)
#     user_profile_id = serializers.PrimaryKeyRelatedField(many=True, required=False, source='user_profile',write_only=True, queryset=UserProfile.objects.all())
#     class Meta:
#         model=Course
#         fields = "__all__"

#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         request = self.context.get('request')
#         if request and request.user.is_authenticated and not request.user.is_staff:
#             self.fields.pop('user_profile_id', None)




from rest_framework import serializers
from courses.models import Course, UserSavedCourse
from accounts.models import UserProfile


class UserProfileNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = "__all__"


class CoursesSerializer(serializers.ModelSerializer):
    # Same output key as before
    user_profile = serializers.SerializerMethodField(read_only=True)

    # Same input key as before
    user_profile_id = serializers.PrimaryKeyRelatedField(
        many=True,
        required=False,
        write_only=True,
        queryset=UserProfile.objects.all(),
    )

    class Meta:
        model = Course
        fields = "__all__"  # includes model fields + user_profile + user_profile_id

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Keep old behavior: hide user_profile_id for non-staff authenticated users
        request = self.context.get("request")
        if request and request.user.is_authenticated and not request.user.is_staff:
            self.fields.pop("user_profile_id", None)

        # Scraped course fields should be read-only (API should not modify scraper data)
        for name, field in self.fields.items():
            if name not in ("user_profile", "user_profile_id"):
                field.read_only = True

    def get_user_profile(self, obj):
        # obj.course_id comes from the scraper table
        user_ids = (
            UserSavedCourse.objects
            .filter(course_id=obj.course_id)
            .values_list("user_profile_id", flat=True)
        )
        profiles = UserProfile.objects.filter(id__in=user_ids)
        return UserProfileNestedSerializer(profiles, many=True, context=self.context).data

    def _sync_user_links(self, course_obj, profiles):
        """
        Make UserSavedCourse links match exactly the given profiles list.
        """
        new_ids = {p.id for p in profiles}

        existing_ids = set(
            UserSavedCourse.objects
            .filter(course_id=course_obj.course_id)
            .values_list("user_profile_id", flat=True)
        )

        # delete removed
        UserSavedCourse.objects.filter(
            course_id=course_obj.course_id,
            user_profile_id__in=(existing_ids - new_ids),
        ).delete()

        # add new
        UserSavedCourse.objects.bulk_create(
            [
                UserSavedCourse(course_id=course_obj.course_id, user_profile_id=pid)
                for pid in (new_ids - existing_ids)
            ],
            ignore_conflicts=True,
        )

    def create(self, validated_data):
        """
        Since Course data is scraped, we don't create Course rows from API.
        But to preserve behavior, allow creating/setting relationships by providing `course_id`
        in request payload (must already exist in scraper table).
        """
        profiles = validated_data.pop("user_profile_id", [])
        course_id = self.initial_data.get("course_id")

        if not course_id:
            raise serializers.ValidationError({"course_id": "course_id is required."})

        try:
            course_obj = Course.objects.get(course_id=course_id)
        except Course.DoesNotExist:
            raise serializers.ValidationError({"course_id": "Course not found in scraper table."})

        if profiles is not None:
            self._sync_user_links(course_obj, profiles)

        return course_obj

    def update(self, instance, validated_data):
        """
        Preserve old functionality: update relationship only.
        """
        profiles = validated_data.pop("user_profile_id", None)

        if profiles is not None:
            self._sync_user_links(instance, profiles)

        return instance
