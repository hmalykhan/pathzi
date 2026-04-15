from __future__ import annotations

from typing import Iterable, Optional
from django.contrib.auth.models import User

from accounts.models import UserProfile


def clean_text(value: Optional[str], max_chars: int = 200) -> str:
    if not value:
        return ""

    value = str(value).strip()
    value = " ".join(value.split())

    if len(value) > max_chars:
        value = value[: max_chars - 3].rstrip() + "..."

    return value

def normalize_profile_value(value: Optional[str], max_chars: int = 200) -> str:
    cleaned = clean_text(value, max_chars=max_chars)
    if not cleaned:
        return ""

    junk_values = {
        "full",
        "n/a",
        "na",
        "none",
        "null",
        "unknown",
        "-",
        "--",
    }

    if cleaned.lower() in junk_values:
        return ""

    return cleaned


def unique_nonempty(values: Iterable[str], max_items: Optional[int] = None) -> list[str]:
    seen = set()
    result = []

    for value in values:
        cleaned = clean_text(value, max_chars=160)
        if not cleaned:
            continue

        key = cleaned.lower()
        if key in seen:
            continue

        seen.add(key)
        result.append(cleaned)

        if max_items is not None and len(result) >= max_items:
            break

    return result


def get_user_profile(user: User) -> Optional[UserProfile]:
    """
    Safely fetch the related UserProfile for a Django User.
    """
    try:
        return UserProfile.objects.get(appuser=user)
    except UserProfile.DoesNotExist:
        return None


def career_label(career) -> str:
    parts = []

    title = clean_text(getattr(career, "jobname", ""), max_chars=100)
    career_type = clean_text(getattr(career, "career_type", ""), max_chars=60)
    sub_type = clean_text(getattr(career, "sub_type", ""), max_chars=60)

    if title:
        parts.append(title)

    meta = [x for x in [career_type, sub_type] if x]
    if meta:
        parts.append(f"({' - '.join(meta)})")

    return " ".join(parts).strip()


def build_user_profile_text(user: User, category: str) -> str:
    """
    Build semantic profile text from UserProfile.

    Strong usable fields in your schema:
    - education_level
    - discipline
    - category (list[str])
    - report (list[str])
    """
    profile = get_user_profile(user)
    if not profile:
        return ""

    sections = []

    education_level = normalize_profile_value(profile.education_level, max_chars=80)
    # discipline = normalize_profile_value(profile.discipline, max_chars=100)
    age = normalize_profile_value(profile.age, max_chars=40)
    # city = normalize_profile_value(profile.city, max_chars=80)

    categories = unique_nonempty(profile.category or [], max_items=8)
    # report_items = unique_nonempty(profile.report or [], max_items=4)

    summary_lines = []

    if education_level:
        summary_lines.append(f"Education level: {education_level}.")
    # if discipline:
    #     summary_lines.append(f"Discipline or field of interest: {discipline}.")
    if age:
        summary_lines.append(f"Age group or stage: {age}.")
    # if city:
    #     summary_lines.append(f"City: {city}.")

    if summary_lines:
        sections.append("Profile:\n" + "\n".join(summary_lines))

    if category:
        sections.append(f"Interest categoriy : {category}")

    # if categories:
    #     sections.append(
    #         "Interest categories:\n" +
    #         "\n".join(f"- {item}" for item in categories)
    #     )

    # if report_items:
    #     cleaned_report_items = [clean_text(item, max_chars=220) for item in report_items]
    #     sections.append(
    #         "Additional user preference signals:\n" +
    #         "\n".join(f"- {item}" for item in cleaned_report_items)
    #     )

    return "\n\n".join(section for section in sections if section.strip())


def build_user_behavior_text(
    saved_careers: Optional[Iterable] = None,
    explored_careers: Optional[Iterable] = None,
) -> str:
    sections = []

    saved_labels = unique_nonempty(
        [career_label(career) for career in (saved_careers or [])],
        max_items=5,
    )

    explored_labels = unique_nonempty(
        [career_label(career) for career in (explored_careers or [])],
        max_items=5,
    )

    saved_lower = {x.lower() for x in saved_labels}
    explored_labels = [x for x in explored_labels if x.lower() not in saved_lower]

    if saved_labels:
        sections.append(
            "Strong signals from saved careers:\n" +
            "\n".join(f"- {item}" for item in saved_labels)
        )

    if explored_labels:
        sections.append(
            "Weaker signals from explored careers:\n" +
            "\n".join(f"- {item}" for item in explored_labels)
        )

    return "\n\n".join(section for section in sections if section.strip())


def build_user_career_text(
    user: User,
    category:str,
    saved_careers: Optional[Iterable] = None,
    explored_careers: Optional[Iterable] = None,
) -> str:
    sections = ["Career recommendation profile"]

    profile = get_user_profile(user)

    profile_text = build_user_profile_text(user, category)
    behavior_text = build_user_behavior_text(
        saved_careers=saved_careers,
        explored_careers=explored_careers,
    )

    if profile_text:
        sections.append(profile_text)

    if behavior_text:
        sections.append(behavior_text)

    summary_fragments = []

    if profile:
        discipline = normalize_profile_value(profile.discipline, max_chars=80)
        education_level = normalize_profile_value(profile.education_level, max_chars=80)
        categories = unique_nonempty(profile.category or [], max_items=4)

        if education_level:
            summary_fragments.append(f"education level {education_level}")
        # if discipline:
        #     summary_fragments.append(f"background in {discipline}")
        if categories:
            summary_fragments.append("interest in " + ", ".join(categories))

    if saved_careers:
        saved_names = unique_nonempty(
            [clean_text(getattr(career, "jobname", ""), max_chars=60) for career in saved_careers],
            max_items=3,
        )
        if saved_names:
            summary_fragments.append("strong interest in " + ", ".join(saved_names))

    if explored_careers:
        saved_name_set = {
            x.lower()
            for x in unique_nonempty(
                [clean_text(getattr(career, "jobname", ""), max_chars=60) for career in (saved_careers or [])],
                max_items=10,
            )
        }

        explored_names = unique_nonempty(
            [clean_text(getattr(career, "jobname", ""), max_chars=60) for career in explored_careers],
            max_items=3,
        )
        explored_names = [x for x in explored_names if x.lower() not in saved_name_set]

        if explored_names:
            summary_fragments.append("some exploration of " + ", ".join(explored_names))

    if summary_fragments:
        sections.append(
            "Overall career intent:\n"
            + "This user has "
            + "; ".join(summary_fragments)
            + "."
        )

    return "\n\n".join(section for section in sections if section.strip())