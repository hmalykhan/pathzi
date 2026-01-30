# apprenticeship/models.py
from django.db import models
from accounts.models import UserProfile

SCRAPED_VACANCY_TABLE = "apprenticeship_apprenticeshipvacancy"
SCRAPED_SCRAPELOG_TABLE = "apprenticeship_apprenticeshipscrapelog"


class ApprenticeshipScrapeLog(models.Model):
    id = models.BigAutoField(primary_key=True)

    run_id = models.UUIDField()
    created_at = models.DateTimeField()

    category = models.CharField(max_length=255)
    keyword = models.CharField(max_length=255)
    start_url = models.CharField(max_length=1000)

    vacancy_ref = models.CharField(max_length=32)

    status = models.CharField(max_length=20)
    message = models.TextField()

    class Meta:
        managed = False
        db_table = SCRAPED_SCRAPELOG_TABLE


class ApprenticeshipVacancy(models.Model):
    id = models.BigAutoField(primary_key=True)

    vacancy_ref = models.CharField(unique=True, max_length=32)
    vacancy_url = models.CharField(max_length=1000)

    category = models.CharField(max_length=255)
    subcategory = models.CharField(max_length=255)
    image_url = models.URLField(max_length=1000, blank=True, default="")

    title = models.CharField(max_length=500)
    employer_name = models.CharField(max_length=500)
    location_summary = models.CharField(max_length=255)

    closing_text = models.CharField(max_length=255)
    posted_text = models.CharField(max_length=255)

    summary_text = models.TextField()
    requirement_summery = models.TextField(blank=True, default="")

    wage = models.CharField(max_length=255)
    wage_extra = models.TextField()

    training_course = models.CharField(max_length=500)
    hours = models.CharField(max_length=500)
    hours_per_week = models.CharField(max_length=64)

    start_date = models.CharField(max_length=255)
    duration = models.CharField(max_length=255)
    positions_available = models.CharField(max_length=64)

    work_intro = models.TextField()
    what_youll_do_heading = models.CharField(max_length=255)
    what_youll_do_items = models.TextField()

    where_youll_work_name = models.CharField(max_length=500)
    where_youll_work_address = models.TextField()

    training_intro = models.TextField()
    training_provider = models.CharField(max_length=500)
    training_course_repeat = models.CharField(max_length=500)

    what_youll_learn_items = models.TextField()
    training_schedule = models.TextField()
    more_training_information = models.TextField()

    essential_qualifications = models.TextField()
    skills_items = models.TextField()
    other_requirements_items = models.TextField()

    about_employer = models.TextField()
    employer_website = models.CharField(max_length=1000)

    company_benefits_items = models.TextField()
    after_this_apprenticeship = models.TextField()

    contact_name = models.CharField(max_length=500)

    scraped_at = models.DateTimeField()
    last_checked_at = models.DateTimeField(blank=True, null=True)

    last_scrape_status = models.CharField(max_length=20)
    last_scrape_message = models.TextField()
    last_scrape_run_id = models.UUIDField(blank=True, null=True)

    city = models.CharField(max_length=100, blank=True, default="")
    state = models.CharField(max_length=100, blank=True, default="")
    zip_code = models.CharField(max_length=20, blank=True, default="")

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        managed = False
        db_table = SCRAPED_VACANCY_TABLE


# ✅ Backward compatibility (same idea as Course/Job proxy)
class Apprenticeship(ApprenticeshipVacancy):
    class Meta:
        proxy = True


class UserSavedApprenticeship(models.Model):
    """
    ✅ API-owned join table for saved apprenticeships.
    Stores vacancy_ref string to avoid FK constraints to unmanaged table.
    """
    user_profile = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name="apprenticeship_links"
    )
    vacancy_ref = models.CharField(max_length=32, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pathzi_user_saved_apprenticeship"
        unique_together = ("user_profile", "vacancy_ref")
        indexes = [
            models.Index(fields=["user_profile"]),
            models.Index(fields=["vacancy_ref"]),
        ]
