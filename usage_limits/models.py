from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class CareerSwipeUsage(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="swipe_usage"
    )

    swipes_used = models.IntegerField(default=0)
    max_swipes = models.IntegerField(default=5)

    updated_at = models.DateTimeField(auto_now=True)

    def remaining_swipes(self):
        return self.max_swipes - self.swipes_used

    def __str__(self):
        return f"{self.user.email} - {self.swipes_used}/{self.max_swipes}"