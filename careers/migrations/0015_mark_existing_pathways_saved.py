"""
Every pathway that exists today was saved deliberately.

Before this change there was no such thing as an unsaved pathway: a row
existed only because the user pressed Save in the app. The new
`user_saved` flag defaults to False, and "My saved pathways" now lists
only flagged rows - so without this migration every user would open the
app and find their saved pathways gone.
"""
from django.db import migrations


def mark_existing_as_saved(apps, schema_editor):
    UserCareerReport = apps.get_model("careers", "UserCareerReport")
    updated = UserCareerReport.objects.update(user_saved=True)
    print("    marked %d existing pathways as user-saved" % updated)


def unmark(apps, schema_editor):
    # Reversing cannot know which rows were saved before this ran, and
    # guessing would hide someone's pathway. Left alone deliberately.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("careers", "0014_usercareerreport_profile_fingerprint_and_more"),
    ]

    operations = [
        migrations.RunPython(mark_existing_as_saved, unmark),
    ]
