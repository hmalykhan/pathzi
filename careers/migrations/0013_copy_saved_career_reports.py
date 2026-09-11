from django.db import migrations
from django.db.models import Q


def copy_reports(apps, schema_editor):
    """Reports used to live on UserSavedCareer; give each one its own row."""
    UserSavedCareer = apps.get_model("careers", "UserSavedCareer")
    UserCareerReport = apps.get_model("careers", "UserCareerReport")
    rows = (
        UserSavedCareer.objects.filter(Q(report_status=True) | ~Q(report={}))
        .values("user_profile_id", "career_id", "report", "report_status", "generated_at")
    )
    UserCareerReport.objects.bulk_create(
        [UserCareerReport(**row) for row in rows], ignore_conflicts=True
    )


class Migration(migrations.Migration):

    dependencies = [
        ("careers", "0012_usercareerreport"),
    ]

    operations = [
        migrations.RunPython(copy_reports, migrations.RunPython.noop),
    ]
