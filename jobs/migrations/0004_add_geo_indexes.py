# jobs/migrations/0004_add_geo_indexes.py
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # needed for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("jobs", "0003_dwpjob_jobscrapelog_usersavedjob_delete_job_and_more"),
    ]

    operations = [
        # B-tree indexes for city and zip_code to optimize autocomplete queries
        # These support istartswith and icontains efficiently
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS job_dwpjob_city_btree_idx
            ON job_dwpjob (city text_pattern_ops);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS job_dwpjob_city_btree_idx;
            """,
        ),
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS job_dwpjob_zip_btree_idx
            ON job_dwpjob (zip_code text_pattern_ops);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS job_dwpjob_zip_btree_idx;
            """,
        ),
    ]
