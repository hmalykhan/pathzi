# jobs/admin.py
from django.contrib import admin
from .models import DwpJob, JobScrapeLog, Job

try:
    admin.site.unregister(Job)
except admin.sites.NotRegistered:
    pass

admin.site.register(DwpJob)
admin.site.register(JobScrapeLog)
