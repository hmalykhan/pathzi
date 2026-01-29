# courses/migrations/0003_add_geo_indexes.py
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # needed for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("courses", "0002_course_search_indexes"),
    ]

    operations = [
        # B-tree indexes for city and zip_code to optimize autocomplete queries
        # These support istartswith and icontains efficiently
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS course_ncscourse_city_btree_idx
            ON course_ncscourse (city text_pattern_ops);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS course_ncscourse_city_btree_idx;
            """,
        ),
        migrations.RunSQL(
            sql="""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS course_ncscourse_zip_btree_idx
            ON course_ncscourse (zip_code text_pattern_ops);
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS course_ncscourse_zip_btree_idx;
            """,
        ),
    ]
