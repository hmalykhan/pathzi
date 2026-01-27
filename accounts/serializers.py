from rest_framework import serializers
from django.contrib.auth.models import User
from django.apps import apps

from .models import UserProfile, Coordinates


class FlexibleStringListField(serializers.ListField):
    """
    Accepts:
      - "administration"
      - ["administration", "it"]
      - null
    Always stores as list of strings.
    """
    def to_internal_value(self, data):
        if data is None:
            return []
        if isinstance(data, str):
            data = [data]
        return super().to_internal_value(data)


class CoordinatesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coordinates
        fields = ["id", "title", "latitude", "longitude", "postal_code", "state", "city", "active"]
        read_only_fields = ["id"]


class UserProfileSerializer(serializers.ModelSerializer):
    appuser = serializers.StringRelatedField(read_only=True)

    # existing functionality
    courses = serializers.SerializerMethodField()
    jobs = serializers.SerializerMethodField()
    apprenticeships = serializers.SerializerMethodField()
    careers = serializers.SerializerMethodField()

    # ✅ now writable + readable (no more SerializerMethodField)
    coordinates = CoordinatesSerializer(many=True, required=False)

    # ✅ accept string or list
    category = FlexibleStringListField(
        child=serializers.CharField(max_length=200),
        required=False,
        allow_empty=True
    )

    report = FlexibleStringListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True
    )

    class Meta:
        model = UserProfile
        fields = "__all__"

    def validate_category(self, value):
        cleaned, seen = [], set()
        for item in value or []:
            item = (item or "").strip()
            if not item:
                continue
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(item)
        return cleaned

    def validate_report(self, value):
        cleaned, seen = [], set()
        for item in value or []:
            item = (item or "").strip()
            if not item:
                continue
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(item)
        return cleaned

    def update(self, instance, validated_data):
        coords_data = validated_data.pop("coordinates", None)

        # update profile fields normally
        instance = super().update(instance, validated_data)

        # if coordinates provided, upsert (won't delete existing unless you want)
        if coords_data is not None:
            for item in coords_data:
                coord_id = item.get("id", None)

                # if id provided -> update existing (only if belongs to this profile)
                if coord_id:
                    Coordinates.objects.filter(id=coord_id, user_profile=instance).update(
                        title=item.get("title"),
                        latitude=item.get("latitude"),
                        longitude=item.get("longitude"),
                        postal_code=item.get("postal_code"),
                        state=item.get("state"),
                        city=item.get("city"),
                        active=item.get("active", True),
                    )
                else:
                    Coordinates.objects.create(user_profile=instance, **item)

        return instance

    # ------- EXISTING METHODS (unchanged behavior) -------

    def get_courses(self, obj):
        Course = apps.get_model("courses", "Course")
        UserSavedCourse = apps.get_model("courses", "UserSavedCourse")

        course_ids = UserSavedCourse.objects.filter(
            user_profile=obj
        ).values_list("course_id", flat=True)

        qs = Course.objects.filter(course_id__in=course_ids)

        class CourseFullSerializer(serializers.ModelSerializer):
            class Meta:
                model = Course
                fields = "__all__"

        return CourseFullSerializer(qs, many=True, context=self.context).data

    def get_jobs(self, obj):
        Job = apps.get_model("jobs", "Job")
        UserSavedJob = apps.get_model("jobs", "UserSavedJob")

        job_ids = UserSavedJob.objects.filter(
            user_profile=obj
        ).values_list("job_id", flat=True)

        qs = Job.objects.filter(job_id__in=job_ids)

        class JobFullSerializer(serializers.ModelSerializer):
            class Meta:
                model = Job
                fields = "__all__"

        return JobFullSerializer(qs, many=True, context=self.context).data

    def get_apprenticeships(self, obj):
        Apprenticeship = apps.get_model("apprenticeship", "Apprenticeship")
        UserSavedApprenticeship = apps.get_model("apprenticeship", "UserSavedApprenticeship")

        vacancy_refs = UserSavedApprenticeship.objects.filter(
            user_profile=obj
        ).values_list("vacancy_ref", flat=True)

        qs = Apprenticeship.objects.filter(vacancy_ref__in=vacancy_refs)

        class ApprenticeshipFullSerializer(serializers.ModelSerializer):
            class Meta:
                model = Apprenticeship
                fields = "__all__"

        return ApprenticeshipFullSerializer(qs, many=True, context=self.context).data

    def get_careers(self, obj):
        Career = apps.get_model("careers", "Career")
        UserSavedCareer = apps.get_model("careers", "UserSavedCareer")

        career_ids = UserSavedCareer.objects.filter(
            user_profile=obj
        ).values_list("career_id", flat=True)

        qs = Career.objects.filter(id__in=career_ids)

        class CareerFullSerializer(serializers.ModelSerializer):
            class Meta:
                model = Career
                fields = "__all__"

        return CareerFullSerializer(qs, many=True, context=self.context).data


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "full_name"]

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already taken.")
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email already registered.")
        return value


class SignUpSerializer(serializers.Serializer):
    username = serializers.CharField()
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    password2 = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError({"password2": "Passwords do not match."})
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class ResetPasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    new_password2 = serializers.CharField(write_only=True, min_length=8)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ForgotPasswordConfirmSerializer(serializers.Serializer):
    uidb64 = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)
    new_password2 = serializers.CharField(write_only=True, min_length=8)


class GoogleAuthSerializer(serializers.Serializer):
    id_token = serializers.CharField()


class UserDataSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField()
    name = serializers.CharField()


class GoogleLoginResponseSerializer(serializers.Serializer):
    status = serializers.BooleanField()
    message = serializers.CharField()
    token = serializers.CharField()
    user = UserDataSerializer()
