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
    
class Qualification(models.Model):
    qulification_type = models.CharField(max_length=200, blank=True)
    subjects = models.CharField(max_length=200, blank=True)
    Grades = models.CharField(max_length=50, blank=True)
    completion_year = models.DateField(blank=True, null=True)

class UserProfile(models.Model):
    appuser = models.ForeignKey(User, on_delete=models.CASCADE, blank = True, null = True)
    age = models.IntegerField(null=True, blank=True)
    study_level = models.CharField(max_length=200, blank=True)
    study_mediam = models.CharField(max_length=200, blank=True)
    amount_to_earn = models.IntegerField(null=True, blank=True)
    career_switcher = models.CharField(max_length=200, blank=True)
    interest = models.CharField(max_length=300, blank=True)
    preference = models.CharField(max_length=200, blank=True)
    qualification = models.ForeignKey(Qualification, on_delete=models.CASCADE, blank = True, null = True)