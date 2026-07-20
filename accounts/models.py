from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError
from pgvector.django import VectorField


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
    apple_sub = models.CharField(
    max_length=255,
    unique=True,
    null=True,
    blank=True,
    db_index=True,
    )
    is_apple_private_email = models.BooleanField(default=False)

    category = models.JSONField(default=list, blank=True)  # list of strings
    qualification = models.JSONField(default=list, blank=True)  # list of strings

    report_status = models.BooleanField(default=False)
    report = models.JSONField(default=list, blank=True)  # list of (long) strings

    # old location fields (keep for backwards compatibility)
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
        validate_string_list(self.qualification, "qualification")
        validate_string_list(self.report, "report")


class Coordinates(models.Model):
    user_profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="coordinates",
    )

    title = models.CharField(max_length=50, blank=True, null=True)  # ✅ NEW

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.title or 'Location'} - {self.city or ''} ({self.latitude}, {self.longitude})"
    


class UserEmbedding(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="embedding_record",
    )

    embedding = VectorField(dimensions=384)

    source_text = models.TextField(blank=True, default="")

    model_name = models.CharField(
        max_length=100,
        blank=True,
        default="all-MiniLM-L6-v2"
    )

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Embedding for user {self.user.id}"
