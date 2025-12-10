from django.db import models
from accounts.models import UserProfile

class Course(models.Model):
    college = models.CharField(max_length=200, blank=True)
    course_name = models.CharField(max_length=200, blank=True)
    course_duration = models.CharField(max_length=50, blank=True)
    location = models.CharField(max_length=200, blank=True)
    fee = models.IntegerField(null=True)
    user_profile = models.ManyToManyField(UserProfile, related_name='courses', blank=True, null=True)
