from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class PasswordResetOTP(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        return self.created_at >= timezone.now() - timedelta(minutes=5)


class UserProfile(models.Model):
    status = models.BooleanField(default=False)
    appuser = models.OneToOneField(User, on_delete=models.CASCADE, blank=True, null=True)

    age = models.CharField(max_length=200, null=True, blank=True)
    education_level = models.CharField(max_length=200, blank=True)
    discipline = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=200, blank=True, null=True)
    zip_code = models.CharField(max_length=200, blank=True)
    address = models.CharField(max_length=300, blank=True)

    category = models.JSONField(default=list, blank=True)  # list of strings

    # ✅ new fields
    report_status = models.BooleanField(default=False)
    report = models.JSONField(default=list, blank=True)  # list of (long) strings


    # ✅ NEW: location
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)


    def clean(self):
        super().clean()

        def validate_string_list(value, field_name):
            if value is None:
                return
            if not isinstance(value, list):
                raise ValidationError({field_name: f"{field_name} must be a list."})
            if not all(isinstance(x, str) for x in value):
                raise ValidationError({field_name: f"Each item in {field_name} must be a string."})

        validate_string_list(self.category, "category")
        validate_string_list(self.report, "report")


class Coordinates(models.Model):
    user_profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="coordinates",
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    active = models.BooleanField(default=True)

