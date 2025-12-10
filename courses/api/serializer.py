from rest_framework import serializers
from courses.models import Course
from accounts.models import UserProfile

class UserProfileNestedSerializer(serializers.ModelSerializer): # Just to avoid the circular imports error, this is called the nested serializer.
    class Meta:
        model = UserProfile
        fields = "__all__"

class CoursesSerializer(serializers.ModelSerializer):
    user_profile = UserProfileNestedSerializer( many=True, read_only=True)
    user_profile_id = serializers.PrimaryKeyRelatedField(many=True, required=False, source='user_profile',write_only=True, queryset=UserProfile.objects.all())
    class Meta:
        model=Course
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and request.user.is_staff:
            self.fields.pop('user_profile', None)
        elif request and request.user.is_authenticated:
            self.fields.pop('user_profile_id', None)
