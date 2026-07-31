"""
Read-only "Data Warehouse" browser over the scraped catalog tables
(courses / apprenticeships / jobs). Staff-only, paginated, city + text search.

List queries select ONLY the light columns needed for the table (never the big
scraped TextFields) so paging stays fast on the 100k+ row tables. The detail
endpoint pulls the curated full record for one row.
"""

from django.db.models import Count, Q

from apprenticeship.models import ApprenticeshipVacancy
from courses.models import NcsCourse
from jobs.models import DwpJob

# Per-dataset config: model, the light columns for the list table, the fields
# used for the free-text search, and the curated field set for the detail view.
DATASETS = {
    "courses": {
        "model": NcsCourse,
        "list": ["id", "course_name", "college_name", "awarding_organization",
                 "cost", "course_qualification_level", "city"],
        "search": ["course_name", "college_name", "awarding_organization", "category"],
        "detail": [
            "id", "course_name", "college_name", "awarding_organization",
            "cost", "cost_description", "course_qualification_level", "learning_method",
            "course_hours", "duration", "attendance_pattern", "course_type",
            "category", "subcategory", "city", "address", "zip_code",
            "email", "phone", "website", "course_url", "image_url",
            "course_description", "who_this_course_is_for", "entry_reeq",
            "requirement_summery",
        ],
    },
    "apprenticeships": {
        "model": ApprenticeshipVacancy,
        "list": ["id", "title", "employer_name", "wage", "duration", "city"],
        "search": ["title", "employer_name", "category"],
        "detail": [
            "id", "title", "employer_name", "wage", "wage_extra",
            "city", "location_summary", "where_youll_work_address", "zip_code",
            "duration", "hours", "hours_per_week", "start_date", "positions_available",
            "category", "subcategory", "training_provider", "training_course",
            "summary_text", "requirement_summery", "what_youll_do_items",
            "essential_qualifications", "skills_items", "about_employer",
            "employer_website", "vacancy_url", "image_url", "closing_text", "posted_text",
        ],
    },
    "jobs": {
        "model": DwpJob,
        "list": ["id", "title", "company", "salary", "job_type", "city"],
        "search": ["title", "company", "category"],
        "detail": [
            "id", "title", "company", "salary", "additional_salary_information",
            "city", "state", "location", "zip_code",
            "job_type", "hours", "remote_working", "posting_date", "closing_date",
            "category", "subcategory", "job_reference",
            "listing_snippet", "summary_intro", "summary_bullets",
            "what_youll_do", "skills_youll_need", "requirement_summery",
            "job_url", "apply_url", "image_url",
        ],
    },
}


def warehouse_cities(dataset):
    """
    Distinct cities for a dataset, ordered by how many records they have
    (busiest cities at the top of the dropdown), then alphabetically.
    """
    cfg = DATASETS[dataset]
    rows = (
        cfg["model"].objects
        .exclude(city__isnull=True).exclude(city="")
        .values("city").annotate(n=Count("id")).order_by("-n", "city")
    )
    return {"dataset": dataset, "cities": [r["city"] for r in rows]}


def warehouse_list(dataset, q=None, city=None, offset=0, limit=50):
    """Paginated light list for one dataset, with optional city + text search."""
    cfg = DATASETS[dataset]
    qs = cfg["model"].objects.all()
    if city:
        qs = qs.filter(city__iexact=city)
    if q:
        cond = Q()
        for f in cfg["search"]:
            cond |= Q(**{f + "__icontains": q})
        qs = qs.filter(cond)

    total = qs.count()
    # Order by pk for stable, index-backed pagination (name-sort would scan).
    rows = list(qs.order_by("id").values(*cfg["list"])[offset:offset + limit])
    return {"dataset": dataset, "total": total, "results": rows}


def warehouse_detail(dataset, obj_id):
    """Curated full record for one row (empty dict if not found)."""
    cfg = DATASETS[dataset]
    return cfg["model"].objects.filter(id=obj_id).values(*cfg["detail"]).first() or {}
