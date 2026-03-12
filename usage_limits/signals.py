# usage_limits/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import CareerSwipeUsage

User = get_user_model()


@receiver(post_save, sender=User)
def create_swipe_usage(sender, instance, created, **kwargs):
    if created:
        CareerSwipeUsage.objects.create(user=instance)