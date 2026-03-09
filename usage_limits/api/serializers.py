from rest_framework import serializers
from usage_limits.models import CareerSwipeUsage


class SwipeStatusSerializer(serializers.ModelSerializer):

    remaining_swipes = serializers.SerializerMethodField()

    class Meta:
        model = CareerSwipeUsage
        fields = [
            "swipes_used",
            "max_swipes",
            "remaining_swipes"
        ]

    def get_remaining_swipes(self, obj):
        return obj.max_swipes - obj.swipes_used


class UpdateSwipeSerializer(serializers.Serializer):
    swipes_used = serializers.IntegerField(required=False, min_value=0)
    max_swipes = serializers.IntegerField(required=False, min_value=1)

    def validate(self, attrs):
        request = self.context["request"]
        usage, _ = CareerSwipeUsage.objects.get_or_create(user=request.user)

        swipes_used = attrs.get("swipes_used", usage.swipes_used)
        max_swipes = attrs.get("max_swipes", usage.max_swipes)

        if max_swipes < swipes_used:
            raise serializers.ValidationError(
                "max_swipes cannot be less than swipes_used"
            )

        return attrs