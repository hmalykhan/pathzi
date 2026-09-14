import uuid

from django.db import migrations


def fill_account_uuid(apps, schema_editor):
    """
    Give every existing profile its own purchase id. A field default cannot do
    this: Django would apply one value to every row and break the unique index.
    """
    UserProfile = apps.get_model("accounts", "UserProfile")
    rows = list(UserProfile.objects.filter(account_uuid__isnull=True).only("id"))
    for row in rows:
        row.account_uuid = uuid.uuid4()
    UserProfile.objects.bulk_update(rows, ["account_uuid"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0027_trial_and_account_uuid"),
    ]

    operations = [
        migrations.RunPython(fill_account_uuid, migrations.RunPython.noop),
    ]
