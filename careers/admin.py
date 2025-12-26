# careers/admin.py
from django.contrib import admin
from .models import CareerJob, CareerScrapeLog, Career

# avoid showing proxy + real model both
try:
    admin.site.unregister(Career)
except admin.sites.NotRegistered:
    pass

admin.site.register(CareerJob)
admin.site.register(CareerScrapeLog)
