# jobs/migrations/0005_add_spatial_indexes.py
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # needed for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("jobs", "0004_add_geo_indexes"),
    ]

    operations = [
        # Spatial index for lat/lon bounding box queries (most important!)
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS job_dwpjob_lat_lon_idx
            ON job_dwpjob (latitude, longitude);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS job_dwpjob_lat_lon_idx;
            """,
        ),
        
        # Individual indexes for category filtering
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS job_dwpjob_category_idx
            ON job_dwpjob (category);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS job_dwpjob_category_idx;
            """,
        ),
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS job_dwpjob_subcategory_idx
            ON job_dwpjob (subcategory);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS job_dwpjob_subcategory_idx;
            """,
        ),
        
        # Compound index for category + spatial queries (common pattern)
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS job_dwpjob_cat_lat_lon_idx
            ON job_dwpjob (category, latitude, longitude);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS job_dwpjob_cat_lat_lon_idx;
            """,
        ),
    ]
