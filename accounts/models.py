from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError
    
class PasswordResetOTP(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        return self.created_at >= timezone.now() - timedelta(minutes=5)
    

class UserProfile(models.Model):
    status = models.BooleanField(default=False)
    appuser = models.OneToOneField(User, on_delete=models.CASCADE, blank=True, null = True)
    age = models.IntegerField(null=True, blank=True)
    education_level = models.CharField(max_length=200, blank=True)
    discipline = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=200, blank=True, null=True)
    zip_code = models.CharField(max_length=200, blank=True)
    address = models.CharField(max_length=300, blank=True)
    category = models.JSONField(default=list, blank=True)  # list of strings

    def clean(self):
        super().clean()
        if self.category is None:
            return
        if not isinstance(self.category, list):
            raise ValidationError({"category": "Category must be a list."})
        if not all(isinstance(x, str) for x in self.category):
            raise ValidationError({"category": "Each category must be a string."})