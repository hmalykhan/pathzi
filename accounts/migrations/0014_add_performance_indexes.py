from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_alter_userprofile_category'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Add index on auth_user.email for faster lookups
                'CREATE INDEX IF NOT EXISTS auth_user_email_idx ON auth_user (email);',
                # Add case-insensitive index for email lookups
                'CREATE INDEX IF NOT EXISTS auth_user_email_lower_idx ON auth_user (LOWER(email));',
            ],
            reverse_sql=[
                'DROP INDEX IF EXISTS auth_user_email_idx;',
                'DROP INDEX IF EXISTS auth_user_email_lower_idx;',
            ]
        ),
    ]
