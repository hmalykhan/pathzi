"""
Career card lists that aren't personalised.

A career is stored once per label it belongs to - "Accounting technician" is
four rows (two sector labels, two category labels) - so a plain filter returns
the same career several times. These helpers return each career once.
"""
import random
from collections import defaultdict

from django.db.models import Subquery

from careers.models import Career

CARD_FIELDS = ("id", "sub_type", "jobname", "job_description", "dg_image_url", "salary")

GUEST_PER_PICKED_CATEGORY = 50  # guest picked some categories
GUEST_PER_CATEGORY = 30         # guest picked nothing


def _interleave_unique(buckets):
    """Take one from each bucket in turn, skipping careers already taken. Returns ids."""
    ids, seen = [], set()
    for i in range(max((len(b) for b in buckets), default=0)):
        for bucket in buckets:
            if i < len(bucket):
                career_id, slug = bucket[i]
                if slug not in seen:
                    seen.add(slug)
                    ids.append(career_id)
    return ids


def guest_deck(picked_keys, rnd=random):
    """
    Guest preview list for /careers/filter/.

      - categories picked: up to 50 random careers from each, in the order picked
      - nothing picked:    30 random careers from each of the 25 categories

    Each career appears once, and categories alternate so the first cards vary.
    `picked_keys` are normalised labels (see accounts.services.user_service.norm_key).
    """
    if picked_keys:
        rows = Career.objects.filter(normalized_sub_type__in=picked_keys)
        per_bucket = GUEST_PER_PICKED_CATEGORY
    else:
        # Only the 25 "category" labels: the 15 "sector" labels are a second
        # grouping of the same careers and would only add repeats.
        rows = Career.objects.filter(career_type=Career.CareerType.CATEGORY)
        per_bucket = GUEST_PER_CATEGORY

    by_key = defaultdict(list)
    for career_id, key, slug in rows.values_list("id", "normalized_sub_type", "job_slug"):
        by_key[key].append((career_id, slug))

    if picked_keys:
        keys = [k for k in dict.fromkeys(picked_keys) if k in by_key]
    else:
        keys = list(by_key)
        rnd.shuffle(keys)

    buckets = [rnd.sample(by_key[k], min(per_bucket, len(by_key[k]))) for k in keys]
    ids = _interleave_unique(buckets)

    cards = Career.objects.only(*CARD_FIELDS).in_bulk(ids)
    return [cards[i] for i in ids if i in cards]


def unique_careers(qs):
    """One row per career from `qs` (its lowest id), ordered by id."""
    first_rows = qs.order_by("job_slug", "id").distinct("job_slug").values("id")
    return Career.objects.filter(id__in=Subquery(first_rows)).order_by("id")
