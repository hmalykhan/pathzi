# courses/migrations/0004_add_spatial_indexes.py
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # needed for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("courses", "0003_add_geo_indexes"),
    ]

    operations = [
        # Spatial index for lat/lon bounding box queries
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS course_ncscourse_lat_lon_idx
            ON course_ncscourse (latitude, longitude);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS course_ncscourse_lat_lon_idx;
            """,
        ),
        
        # Individual indexes for category filtering
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS course_ncscourse_category_idx
            ON course_ncscourse (category);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS course_ncscourse_category_idx;
            """,
        ),
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS course_ncscourse_subcategory_idx
            ON course_ncscourse (subcategory);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS course_ncscourse_subcategory_idx;
            """,
        ),
        
        # Compound index for category + spatial queries
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS course_ncscourse_cat_lat_lon_idx
            ON course_ncscourse (category, latitude, longitude);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS course_ncscourse_cat_lat_lon_idx;
            """,
        ),
    ]
