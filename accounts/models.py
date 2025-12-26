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
    appuser = models.OneToOneField(User, on_delete=models.CASCADE, blank=True, null = True)
    age = models.IntegerField(null=True, blank=True)
    education_level = models.CharField(max_length=200, blank=True)
    discipline = models.CharField(max_length=200, blank=True)
    city = models.IntegerField(null=True, blank=True)
    zip_code = models.CharField(max_length=200, blank=True)
    address = models.CharField(max_length=300, blank=True)
    category = models.CharField(max_length=200, blank=True)