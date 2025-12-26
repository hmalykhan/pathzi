# apprenticeship/admin.py
from django.contrib import admin
from .models import ApprenticeshipVacancy, ApprenticeshipScrapeLog, Apprenticeship

try:
    admin.site.unregister(Apprenticeship)
except admin.sites.NotRegistered:
    pass

admin.site.register(ApprenticeshipVacancy)
admin.site.register(ApprenticeshipScrapeLog)
