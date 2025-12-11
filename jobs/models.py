from django.db import models
from accounts.models import UserProfile

class Job(models.Model):
    company = models.CharField(max_length=200, blank=True)
    job_name = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=50, blank=True)
    location = models.CharField(max_length=200, blank=True)
    duration = models.CharField(max_length=200, blank=True)
    salary = models.IntegerField(null=True)
    user_profile = models.ManyToManyField(UserProfile, related_name='jobs', blank=True)