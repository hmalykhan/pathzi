from django.db import migrations
import json

def convert_category_to_json(apps, schema_editor):
    UserProfile = apps.get_model("accounts", "UserProfile")

    # This runs BEFORE the column becomes jsonb
    for p in UserProfile.objects.all():
        val = p.category
        if val is None or val == "":
            continue

        # If already looks like JSON list, skip
        # Otherwise convert "Administration" -> ["Administration"]
        if isinstance(val, str):
            # store as JSON string representing list
            p.category = json.dumps([val])
            p.save(update_fields=["category"])

class Migration(migrations.Migration):
    dependencies = [
    ("accounts", "0010_userprofile_status"),
]

    operations = [
        migrations.RunPython(convert_category_to_json),
        # then your AlterField(...) to JSONField happens here
    ]
