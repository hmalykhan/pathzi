# careers/models.py
import uuid
from django.db import models
from accounts.models import UserProfile

SCRAPED_CAREERJOB_TABLE = "fetch_careerjob"
SCRAPED_SCRAPELOG_TABLE = "fetch_jobscrapelog"


class CareerScrapeLog(models.Model):
    id = models.BigAutoField(primary_key=True)

    run_id = models.UUIDField()
    created_at = models.DateTimeField()

    route = models.CharField(max_length=20)
    sub_type = models.CharField(max_length=255)
    job_slug = models.CharField(max_length=255)
    job_url = models.CharField(max_length=1000)

    status = models.CharField(max_length=20)
    message = models.TextField()

    class Meta:
        managed = False
        db_table = SCRAPED_SCRAPELOG_TABLE


class CareerJob(models.Model):
    id = models.BigAutoField(primary_key=True)

    career_type = models.CharField(max_length=20)
    sub_type = models.CharField(max_length=255)
    job_slug = models.CharField(max_length=255)

    job_url = models.CharField(max_length=200)
    jobname = models.CharField(max_length=255)
    job_description = models.TextField()

    salary = models.CharField(max_length=255)
    hours = models.CharField(max_length=255)
    timings = models.CharField(max_length=255)

    how_to_become = models.TextField()
    college = models.TextField()
    college_entry_req = models.TextField()

    apprenticeship_entry_req = models.TextField()
    apprenticeship = models.TextField()

    scraped_at = models.DateTimeField()
    last_checked_at = models.DateTimeField(blank=True, null=True)

    last_scrape_message = models.TextField()
    last_scrape_run_id = models.UUIDField(blank=True, null=True)
    last_scrape_status = models.CharField(max_length=20)

    class Meta:
        managed = False
        db_table = SCRAPED_CAREERJOB_TABLE
        unique_together = (("career_type", "sub_type", "job_slug"),)


# ✅ Backward compatibility: from careers.models import Career
class Career(CareerJob):
    class Meta:
        proxy = True


class UserSavedCareer(models.Model):
    """
    ✅ API-owned join table for save/unsave/my.
    We store the scraper row PK (Career.id).
    """
    user_profile = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name="career_links"
    )
    career_id = models.BigIntegerField(db_index=True)  # stores Career.id
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pathzi_user_saved_career"
        unique_together = ("user_profile", "career_id")
        indexes = [
            models.Index(fields=["user_profile"]),
            models.Index(fields=["career_id"]),
        ]
