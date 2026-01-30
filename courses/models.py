# from django.db import models
# from accounts.models import UserProfile

# class Course(models.Model):
#     college = models.CharField(max_length=200, blank=True)
#     course_name = models.CharField(max_length=200, blank=True)
#     course_duration = models.CharField(max_length=50, blank=True)
#     location = models.CharField(max_length=200, blank=True)
#     fee = models.IntegerField(null=True)
#     user_profile = models.ManyToManyField(UserProfile, related_name='courses', blank=True)



# courses/models.py  (API project)

# courses/models.py  (API project)

# courses/models.py  (API project)

import uuid
from django.db import models
from accounts.models import UserProfile

# These MUST match what you printed from introspection:
# course_ncscourse
# course_coursescrapelog
SCRAPED_NCSCOURSE_TABLE = "course_ncscourse"
SCRAPED_SCRAPELOG_TABLE = "course_coursescrapelog"


class CourseScrapeLog(models.Model):
    # If scraper project used AutoField, change to models.AutoField(primary_key=True)
    id = models.BigAutoField(primary_key=True)

    run_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    created_at = models.DateTimeField()

    category = models.CharField(max_length=255, blank=True, default="")
    keyword = models.CharField(max_length=255, blank=True, default="")
    postcode = models.CharField(max_length=64, blank=True, default="")
    distance = models.IntegerField(default=0)
    start_url = models.URLField(max_length=1000, blank=True, default="")

    course_id = models.UUIDField(null=True, blank=True, db_index=True)

    status = models.CharField(max_length=20, default="")
    message = models.TextField(blank=True, default="")

    class Meta:
        managed = False
        db_table = SCRAPED_SCRAPELOG_TABLE


class NcsCourse(models.Model):
    id = models.BigAutoField(primary_key=True)

    course_id = models.UUIDField(unique=True)

    category = models.CharField(max_length=255, blank=True, default="", db_index=True)
    subcategory = models.CharField(max_length=255, blank=True, default="", db_index=True)

    course_url = models.URLField(max_length=1000)
    image_url = models.URLField(max_length=1000, blank=True, default="")

    course_name = models.CharField(max_length=500, blank=True, default="")
    course_type = models.CharField(max_length=500, blank=True, default="")
    learning_method = models.CharField(max_length=255, blank=True, default="")
    course_hours = models.CharField(max_length=255, blank=True, default="")

    course_stryd_time = models.CharField(max_length=255, blank=True, default="")
    course_qualification_level = models.CharField(max_length=255, blank=True, default="")
    course_description = models.TextField(blank=True, default="")

    attendance_pattern = models.CharField(max_length=255, blank=True, default="")
    awarding_organization = models.CharField(max_length=500, blank=True, default="")

    who_this_course_is_for = models.TextField(blank=True, default="")
    entry_reeq = models.TextField(blank=True, default="")

    college_name = models.CharField(max_length=500, blank=True, default="")
    address = models.TextField(blank=True, default="")

    email = models.CharField(max_length=255, blank=True, default="")
    phone = models.CharField(max_length=255, blank=True, default="")

    website = models.URLField(max_length=1000, blank=True, default="")

    duration = models.CharField(max_length=255, blank=True, default="")

    cost = models.CharField(max_length=255, blank=True, default="")
    cost_description = models.TextField(blank=True, default="")
    requirement_summery = models.TextField(blank=True, default="")

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
        db_table = SCRAPED_NCSCOURSE_TABLE

    def __str__(self):
        return f"{self.course_name} ({self.course_id})"


# Keep your old import working: from courses.models import Course
# This does NOT create a new table.
class Course(NcsCourse):
    class Meta:
        proxy = True


# If you still want the old "ManyToMany like before" behavior,
# keep this API-owned join table.
# IMPORTANT: we store course_id as UUID (no FK constraint) to avoid migration issues.
class UserSavedCourse(models.Model):
    user_profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="course_links",
    )

    # references Course.course_id (in scraper table)
    course_id = models.UUIDField(db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pathzi_user_saved_course"
        unique_together = ("user_profile", "course_id")
        indexes = [
            models.Index(fields=["user_profile"]),
            models.Index(fields=["course_id"]),
        ]
