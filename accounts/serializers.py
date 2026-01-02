from rest_framework import serializers
from django.contrib.auth.models import User
from .models import UserProfile
from qualification.api.serializer import QualificationSerializer
from courses.api.serializer import CoursesSerializer
from jobs.api.serializers import JobsSerializer
from django.apps import apps


class UserProfileSerializer(serializers.ModelSerializer):
    appuser = serializers.StringRelatedField(read_only=True)
    courses = serializers.SerializerMethodField()
    jobs = serializers.SerializerMethodField()
    apprenticeships = serializers.SerializerMethodField()
    careers = serializers.SerializerMethodField()

    # ✅ category as JSON list of strings
    category = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False,
        allow_empty=True
    )

    # ✅ report as JSON list of strings
    report = serializers.ListField(
        child=serializers.CharField(),  # no max_length to allow long strings
        required=False,
        allow_empty=True
    )


    class Meta:
        model = UserProfile
        fields = "__all__"

    def validate_category(self, value):
        """
        Accepts:
          - ["Administration", "IT"]
          - "Administration"   (optional single string)
        Saves:
          - list of non-empty strings
          - stripped
          - unique (case-insensitive)
        """
        if value is None:
            return []

        if isinstance(value, str):
            value = [value]

        cleaned = []
        seen = set()
        for item in value:
            if not item:
                continue
            item = item.strip()
            if not item:
                continue

            key = item.lower()
            if key in seen:
                continue
            seen.add(key)

            cleaned.append(item)  # or item.lower() if you want stored lowercase
        return cleaned
    
    def validate_report(self, value):
        if value is None:
            return []

        if isinstance(value, str):
            value = [value]

        cleaned = []
        seen = set()
        for item in value:
            if not item:
                continue
            item = item.strip()
            if not item:
                continue

            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(item)

        return cleaned

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
        Job = apps.get_model("jobs", "Job")  # proxy mapped to scraper table
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
        Career = apps.get_model("careers", "Career")  # proxy mapped to fetch_careerjob
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
    full_name = serializers.CharField(source='get_full_name', read_only = True)
    class Meta:
        model = User
        fields = ["id", "username", "email", "full_name"]  # don't expose password!
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

    # Removed validate_username and validate_email methods
    # These were causing DB queries during validation
    # Uniqueness is now checked in the view for better performance and control

    def validate(self, attrs):
        if attrs["password"] != attrs["password2"]:
            # can be string OR dict; string is easier for single-message handling
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