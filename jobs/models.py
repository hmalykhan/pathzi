import uuid
from django.db import models
from accounts.models import UserProfile

SCRAPED_DWPJOB_TABLE = "job_dwpjob"
SCRAPED_SCRAPELOG_TABLE = "job_jobscrapelog"


class JobScrapeLog(models.Model):
    # Scraper model didn't define id explicitly; DB table will have one by default.
    id = models.BigAutoField(primary_key=True)

    run_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    created_at = models.DateTimeField()

    category = models.CharField(max_length=255, blank=True, default="")
    subcategory = models.CharField(max_length=255, blank=True, default="")
    start_url = models.URLField(max_length=1000, blank=True, default="")

    job_id = models.CharField(max_length=64, blank=True, default="", db_index=True)

    status = models.CharField(max_length=20, default="")
    message = models.TextField(blank=True, default="")

    class Meta:
        managed = False
        db_table = SCRAPED_SCRAPELOG_TABLE


class DwpJob(models.Model):
    id = models.BigAutoField(primary_key=True)

    job_id = models.CharField(max_length=64, unique=True)

    category = models.CharField(max_length=255, blank=True, default="", db_index=True)
    subcategory = models.CharField(max_length=255, blank=True, default="", db_index=True)

    job_url = models.URLField(max_length=1000, blank=True, default="")
    apply_url = models.URLField(max_length=1000, blank=True, default="")
    image_url = models.URLField(max_length=1000, blank=True, default="")

    title = models.CharField(max_length=500, blank=True, default="")
    company = models.CharField(max_length=500, blank=True, default="")
    location = models.CharField(max_length=500, blank=True, default="")

    posting_date = models.CharField(max_length=255, blank=True, default="")
    closing_date = models.CharField(max_length=255, blank=True, default="")

    hours = models.CharField(max_length=255, blank=True, default="")
    job_type = models.CharField(max_length=255, blank=True, default="")
    job_reference = models.CharField(max_length=255, blank=True, default="")

    salary = models.CharField(max_length=255, blank=True, default="")
    remote_working = models.CharField(max_length=255, blank=True, default="")
    additional_salary_information = models.TextField(blank=True, default="")

    disability_confident = models.BooleanField(default=False)

    listing_snippet = models.TextField(blank=True, default="")

    summary_intro = models.TextField(blank=True, default="")
    summary_bullets = models.TextField(blank=True, default="")

    what_youll_do = models.TextField(blank=True, default="")
    skills_youll_need = models.TextField(blank=True, default="")
    requirement_summery = models.TextField(blank=True, default="")

    raw_text = models.TextField(blank=True, default="")

    scraped_at = models.DateTimeField()
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_scrape_status = models.CharField(max_length=20, blank=True, default="")
    last_scrape_message = models.TextField(blank=True, default="")
    last_scrape_run_id = models.UUIDField(null=True, blank=True, db_index=True)

    city = models.CharField(max_length=100, blank=True, default="")
    state = models.CharField(max_length=100, blank=True, default="")
    zip_code = models.CharField(max_length=20, blank=True, default="")

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        managed = False
        db_table = SCRAPED_DWPJOB_TABLE


# ✅ Backward compatibility: keep imports working: from jobs.models import Job
class Job(DwpJob):
    class Meta:
        proxy = True


class UserSavedJob(models.Model):
    """
    ✅ API-owned join table used for save/unsave/my.
    Stores scraper job_id (string), avoids FK constraints to unmanaged table.
    """
    user_profile = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name="job_links"
    )
    job_id = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pathzi_user_saved_job"
        unique_together = ("user_profile", "job_id")
        indexes = [
            models.Index(fields=["user_profile"]),
            models.Index(fields=["job_id"]),
        ]
