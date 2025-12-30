# courses/migrations/0002_course_search_indexes.py
from django.db import migrations

class Migration(migrations.Migration):
    atomic = False  # needed for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("courses", "0001_initial"),  # <- replace with your actual last migration
    ]

    operations = [
        # 1) pg_trgm extension (safe to run multiple times)
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            reverse_sql="DROP EXTENSION IF EXISTS pg_trgm;",
        ),

        # 2) Trigram index for lower(address) to support your loc_l searches
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS course_ncscourse_addr_trgm_lower_idx
            ON course_ncscourse
            USING GIN (lower(address) gin_trgm_ops);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS course_ncscourse_addr_trgm_lower_idx;
            """,
        ),

        # 3) Functional btree index for lower(category) (matches your annotate(cat_l=Lower("category")))
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS course_ncscourse_cat_lower_idx
            ON course_ncscourse (lower(category));
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS course_ncscourse_cat_lower_idx;
            """,
        ),
    ]
