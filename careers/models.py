# careers/models.py (Recommendation project)
import uuid, re
from django.db import models
from accounts.models import UserProfile
from pgvector.django import VectorField


SCRAPED_CAREERJOB_TABLE = "fetch_careerjob"
SCRAPED_SCRAPELOG_TABLE = "fetch_jobscrapelog"

def normalize_sub_type(value: str) -> str:
    value = value or ""
    value = value.strip().lower()
    value = re.sub(r"[ _-]+", "", value)
    return value


class CareerScrapeLog(models.Model):
    """
    Read-only mapping to the scraper table.
    """
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

    def __str__(self):
        return f"{self.created_at} {self.status} {self.job_slug}"


class CareerJob(models.Model):
    """
    Read-only mapping to the scraper table.
    """
    class CareerType(models.TextChoices):
        SECTOR = "sector", "Sector"
        CATEGORY = "category", "Category"

    id = models.BigAutoField(primary_key=True)

    career_type = models.CharField(max_length=20, choices=CareerType.choices)
    sub_type = models.CharField(max_length=255)
    normalized_sub_type = models.CharField(
        max_length=255,
        db_index=True,   # VERY IMPORTANT
        blank=True,
        default=""
    )

    job_slug = models.SlugField(max_length=255)
    job_url = models.URLField()  # default max_length=200

    image_url = models.URLField(max_length=1000, blank=True, default="")
    dg_image_url = models.URLField(max_length=1000, blank=True, default="")

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
        # Uniqueness is enforced in Postgres by the unique index:
        # (career_type, sub_type, job_slug)

    def save(self, *args, **kwargs):
        self.normalized_sub_type = normalize_sub_type(self.sub_type)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.career_type}:{self.sub_type} - {self.jobname}"


# Backward compatibility: from careers.models import Career
class Career(CareerJob):
    class Meta:
        proxy = True


class UserSavedCareer(models.Model):
    """
    API-owned join table for save/unsave/my.
    Stores scraper row PK (Career.id) as career_id.

    Also stores per-user-per-career report data (user+career oriented).
    """
    user_profile = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name="career_links"
    )
    
    career = models.ForeignKey(
    Career,
    on_delete=models.CASCADE,
    null=False,
    related_name="saved_user_links"
    )

    # ✅ report fields (do NOT break old functionality)
    report_status = models.BooleanField(default=False)
    report = models.JSONField(default=dict, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pathzi_user_saved_career"
        unique_together = ("user_profile", "career")
        indexes = [
            models.Index(fields=["user_profile"]),
            models.Index(fields=["career"]),
        ]

class UserExploredCareer(models.Model):
    user_profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="explored_career_links"
    )
    career = models.ForeignKey(
        Career,
        on_delete=models.CASCADE,
        related_name="explored_user_links"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user_profile", "career")

    def __str__(self):
        return f"{self.user_profile_id} - {self.career_id}"
    

class CareerEmbedding(models.Model):
    career = models.OneToOneField(
        CareerJob,
        on_delete=models.CASCADE,
        related_name="embedding_record",
    )
    embedding = VectorField(dimensions=384)
    source_text = models.TextField(blank=True, default="")
    model_name = models.CharField(max_length=100, blank=True, default="all-MiniLM-L6-v2")
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "fetch_careerembedding"

    def __str__(self):
        return f"Embedding<{self.career_id}>"