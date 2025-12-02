from django.contrib import admin
from django.contrib.auth.models import User
from .models import UserProfile

class CustomUserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'full_name')
    def full_name(self, obj):
        return obj.get_full_name()
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
admin.site.register(UserProfile)