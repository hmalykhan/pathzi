"""
Populate ONLY `searched_career` demo activity rows, without touching any other
data. Each row carries a career + a searched location (activity_value = city
string, metadata = structured location). All rows are tagged metadata['demo']
== True and metadata['kind'] == 'searched_career' so they can be removed cleanly.

Seed:   python scripts/seed_searched_career.py
Clear:  python scripts/seed_searched_career.py --clear
"""

import os
import sys
import random
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pathzi.settings")
django.setup()

from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model

from analytics.models import UserActivity
from analytics import constants as C
from careers.models import Career

random.seed(7)

CITIES = ["London", "Manchester", "Birmingham", "Leeds", "Bristol", "Lahore", "Glasgow"]


def clear():
    deleted = UserActivity.objects.filter(
        activity_type=C.SEARCHED_CAREER, metadata__demo=True
    ).delete()
    print("cleared searched_career demo rows:", deleted)


def seed():
    users = list(get_user_model().objects.all()[:30])
    careers = list(Career.objects.all()[:15])
    if not users or not careers:
        print("Need at least 1 user and some careers in the DB. Aborting.")
        return

    weights = [max(1, 16 - i) for i in range(len(careers))]
    now = timezone.now()
    total = 0

    for day in range(30):
        day_dt = now - timedelta(days=day)
        intensity = 1.0 + (30 - day) / 30.0
        count = int(random.randint(4, 10) * intensity)

        batch = []
        for _ in range(count):
            city = random.choice(CITIES)
            batch.append(
                UserActivity(
                    user=random.choice(users),
                    career=random.choices(careers, weights=weights, k=1)[0],
                    activity_type=C.SEARCHED_CAREER,
                    activity_value=city,
                    metadata={"demo": True, "kind": "searched_career", "city": city},
                )
            )

        created = UserActivity.objects.bulk_create(batch)
        # auto_now_add overrides created_at, so backdate this day's rows.
        UserActivity.objects.filter(id__in=[o.id for o in created]).update(created_at=day_dt)
        total += len(created)

    print(f"seeded searched_career rows: {total}")
    print(f"careers used: {len(careers)} | users used: {len(users)}")


if __name__ == "__main__":
    if "--clear" in sys.argv:
        clear()
    else:
        seed()
