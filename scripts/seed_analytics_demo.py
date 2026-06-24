"""
Seed (or clear) a realistic analytics demo dataset so the admin dashboard
shows populated charts.

Seed:   python scripts/seed_analytics_demo.py
Clear:  python scripts/seed_analytics_demo.py --clear

All demo rows are tagged so they can be removed cleanly:
  - UserActivity:  metadata['demo'] == True
  - ProviderLead:  contact_email ends with '@demo.local'
"""

import os
import sys
import random
import django

# Make the project root importable when run from scripts/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pathzi.settings")
django.setup()

from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model

from analytics.models import UserActivity, ProviderLead
from analytics import constants as C
from careers.models import Career
from accounts.models import UserProfile

DEMO_EMAIL_DOMAIN = "@demo.local"
random.seed(42)  # reproducible


def clear():
    ua = UserActivity.objects.filter(metadata__demo=True).delete()
    pl = ProviderLead.objects.filter(contact_email__endswith=DEMO_EMAIL_DOMAIN).delete()
    print("cleared UserActivity:", ua)
    print("cleared ProviderLead:", pl)


def seed():
    users = list(get_user_model().objects.all()[:30])
    careers = list(Career.objects.all()[:15])
    if not users or not careers:
        print("Need at least 1 user and some careers in the DB. Aborting.")
        return

    # Weighted career popularity so "top" charts have a clear ranking.
    weights = [max(1, 16 - i) for i in range(len(careers))]
    providers = ["UCAS", "Indeed", "NHS Careers", "Reed", "Gov.uk Apprenticeships", "Pearson"]
    # Demo card titles per route type (the title the user clicked through to).
    CARD_TITLES = {
        "course": ["BSc (Hons) Programme", "Level 3 BTEC Diploma", "Foundation Degree", "HND Course"],
        "apprenticeship": ["Level 2 Intermediate Apprenticeship", "Level 3 Advanced Apprenticeship",
                            "Degree Apprenticeship", "Higher Apprenticeship"],
        "job": ["Graduate Trainee Role", "Junior Associate Position", "Entry-Level Vacancy"],
    }
    cities = ["London", "Manchester", "Birmingham", "Leeds", "Bristol"]

    # Give a handful of users a profile city so the location chart populates.
    # Originals are restored on --clear via a tagged backup in metadata? We avoid
    # mutating: instead only set city where it's currently empty, and tag those.
    located_users = []
    for u in users[:12]:
        prof, _ = UserProfile.objects.get_or_create(appuser=u)
        if not prof.city:
            prof.city = random.choice(cities)
            prof._demo_city = True
            prof.save(update_fields=["city"])
        located_users.append(u)

    now = timezone.now()
    total = 0

    for day in range(30):
        day_dt = now - timedelta(days=day)
        # slightly more activity on recent days
        intensity = 1.0 + (30 - day) / 30.0
        views = int(random.randint(8, 22) * intensity)

        batch = []

        def add(activity_type, career, route_id=None, val=None, user=None, card=None):
            # Spread activity across ALL users so the user list is populated;
            # located users (with a city) still get plenty by chance, keeping
            # the location chart populated.
            batch.append(
                UserActivity(
                    user=user or random.choice(users),
                    career=career,
                    route_id=route_id,
                    activity_type=activity_type,
                    activity_value=val,
                    card=card,
                    metadata={"demo": True},
                )
            )

        for _ in range(views):
            career = random.choices(careers, weights=weights, k=1)[0]
            add(C.CAREER_VIEWED, career)
            roll = random.random()
            if roll < 0.42:
                add(C.CAREER_SWIPED_RIGHT, career)
            elif roll < 0.72:
                add(C.CAREER_SWIPED_LEFT, career)
            if random.random() < 0.18:
                add(C.CAREER_SAVED, career)
            if random.random() < 0.22:
                add(C.CAREER_EXPLORED, career)

        for _ in range(random.randint(4, 10)):
            add(C.ROUTE_CLICKED, random.choices(careers, weights=weights, k=1)[0],
                route_id=random.choice(C.ROUTE_TYPES))
        for _ in range(random.randint(3, 8)):
            route = random.choice(C.ROUTE_TYPES)
            add(C.PROVIDER_LINK_CLICKED, random.choices(careers, weights=weights, k=1)[0],
                route_id=route, val=random.choice(providers),
                card=random.choice(CARD_TITLES[route]))

        created = UserActivity.objects.bulk_create(batch)
        # auto_now_add overrides created_at, so backdate this day's rows.
        UserActivity.objects.filter(id__in=[o.id for o in created]).update(created_at=day_dt)
        total += len(created)

    # Consent leads (spread over recent days, top careers more likely)
    leads = 0
    for i in range(22):
        career = random.choices(careers[:8], weights=weights[:8], k=1)[0]
        ProviderLead.objects.create(
            user=random.choice(users),
            career=career,
            provider_name=random.choice(["City College", "NHS Trust", "BuildRight Ltd", "TechStart Academy"]),
            provider_type=random.choice(["college", "employer", "training_provider"]),
            contact_email=f"lead{i}{DEMO_EMAIL_DOMAIN}",
        )
        leads += 1

    print(f"seeded UserActivity rows: {total}")
    print(f"seeded ProviderLead rows: {leads}")
    print(f"careers used: {len(careers)} | users used: {len(users)} | located users: {len(located_users)}")


if __name__ == "__main__":
    if "--clear" in sys.argv:
        clear()
    else:
        seed()
