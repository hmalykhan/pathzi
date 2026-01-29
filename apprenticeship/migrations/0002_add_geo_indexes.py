# apprenticeship/migrations/0002_add_geo_indexes.py
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # needed for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("apprenticeship", "0001_initial"),
    ]

    operations = [
        # B-tree indexes for city and zip_code to optimize autocomplete queries
        # These support istartswith and icontains efficiently
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS apprenticeship_apprenticeshipvacancy_city_btree_idx
            ON apprenticeship_apprenticeshipvacancy (city text_pattern_ops);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS apprenticeship_apprenticeshipvacancy_city_btree_idx;
            """,
        ),
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS apprenticeship_apprenticeshipvacancy_zip_btree_idx
            ON apprenticeship_apprenticeshipvacancy (zip_code text_pattern_ops);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS apprenticeship_apprenticeshipvacancy_zip_btree_idx;
            """,
        ),
    ]
