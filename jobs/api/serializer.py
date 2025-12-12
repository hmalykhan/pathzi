from rest_framework import serializers
from jobs.models import Job
from accounts.models import  UserProfile

class UserProfileNestedSerializer(serializers.ModelSerializer): # Just to avoid the circular imports error, this is called the nested serializer.
    class Meta:
        model = UserProfile
        fields = "__all__"

class JobsSerializer(serializers.ModelSerializer):
    user_profile = UserProfileNestedSerializer(many=True, read_only=True)
    user_profile_id = serializers.PrimaryKeyRelatedField(many=True, write_only=True, queryset = UserProfile.objects.all(), source='user_profile')
    class Meta:
        model = Job
        fields = "__all__"

    def __init__(self,*args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request', None)
        if request and request.user.is_authenticated and not request.user.is_staff:
            self.fields.pop('user_profile_id', None)
