# careers/models.py
import uuid
from django.db import models
from accounts.models import UserProfile

SCRAPED_CAREERJOB_TABLE = "fetch_careerjob"
SCRAPED_SCRAPELOG_TABLE = "fetch_jobscrapelog"


class CareerScrapeLog(models.Model):
    # IMPORTANT:
    # If your DB table has BIGINT id, keep BigAutoField.
    # If it has INT id, change to AutoField.
    id = models.BigAutoField(primary_key=True)

    run_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    created_at = models.DateTimeField()

    route = models.CharField(max_length=20, blank=True, default="")
    sub_type = models.CharField(max_length=255, blank=True, default="")

    job_slug = models.CharField(max_length=255, blank=True, default="")
    job_url = models.URLField(max_length=1000, blank=True, default="")

    status = models.CharField(max_length=20, default="")
    message = models.TextField(blank=True, default="")

    class Meta:
        managed = False
        db_table = SCRAPED_SCRAPELOG_TABLE
        # These don't create indexes because managed=False, but good for “matching”
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["run_id", "created_at"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["route", "sub_type", "created_at"]),
        ]

    def __str__(self):
        return f"{self.created_at} {self.status} {self.job_slug}"


class CareerJob(models.Model):
    class CareerType(models.TextChoices):
        SECTOR = "sector", "Sector"
        CATEGORY = "category", "Category"

    # Same note as above about id type.
    id = models.BigAutoField(primary_key=True)

    career_type = models.CharField(max_length=20, choices=CareerType.choices)
    sub_type = models.CharField(max_length=255)

    job_slug = models.SlugField(max_length=255)
    job_url = models.URLField()  # matches project 1 default (max_length=200)

    image_url = models.URLField(max_length=1000, blank=True, default="")

    jobname = models.CharField(max_length=255)
    job_description = models.TextField(blank=True, default="")

    salary = models.CharField(max_length=255, blank=True, default="")
    hours = models.CharField(max_length=255, blank=True, default="")
    timings = models.CharField(max_length=255, blank=True, default="")

    how_to_become = models.TextField(blank=True, default="")
    college = models.TextField(blank=True, default="")
    college_entry_req = models.TextField(blank=True, default="")
    apprenticeship_entry_req = models.TextField(blank=True, default="")
    apprenticeship = models.TextField(blank=True, default="")

    scraped_at = models.DateTimeField()

    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_scrape_status = models.CharField(max_length=20, blank=True, default="")
    last_scrape_message = models.TextField(blank=True, default="")
    last_scrape_run_id = models.UUIDField(null=True, blank=True, db_index=True)

    class Meta:
        managed = False
        db_table = SCRAPED_CAREERJOB_TABLE
        unique_together = (("career_type", "sub_type", "job_slug"),)

    def __str__(self) -> str:
        return f"{self.career_type}:{self.sub_type} - {self.jobname}"



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
