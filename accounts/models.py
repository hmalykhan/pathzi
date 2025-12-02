from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
    
class UserProfile(models.Model):
    appuser = models.ForeignKey(User, on_delete=models.CASCADE, default=None)
    age = models.IntegerField()
    career_switcher = models.CharField(max_length=200)
    interest = models.CharField(max_length=300)


class PasswordResetOTP(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        return self.created_at >= timezone.now() - timedelta(minutes=5)
