# apprenticeship/migrations/0003_add_spatial_indexes.py
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # needed for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("apprenticeship", "0002_add_geo_indexes"),
    ]

    operations = [
        # Spatial index for lat/lon bounding box queries
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS apprenticeship_apprenticeshipvacancy_lat_lon_idx
            ON apprenticeship_apprenticeshipvacancy (latitude, longitude);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS apprenticeship_apprenticeshipvacancy_lat_lon_idx;
            """,
        ),
        
        # Individual indexes for category filtering
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS apprenticeship_apprenticeshipvacancy_category_idx
            ON apprenticeship_apprenticeshipvacancy (category);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS apprenticeship_apprenticeshipvacancy_category_idx;
            """,
        ),
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS apprenticeship_apprenticeshipvacancy_subcategory_idx
            ON apprenticeship_apprenticeshipvacancy (subcategory);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS apprenticeship_apprenticeshipvacancy_subcategory_idx;
            """,
        ),
        
        # Compound index for category + spatial queries
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS apprenticeship_apprenticeshipvacancy_cat_lat_lon_idx
            ON apprenticeship_apprenticeshipvacancy (category, latitude, longitude);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS apprenticeship_apprenticeshipvacancy_cat_lat_lon_idx;
            """,
        ),
    ]
