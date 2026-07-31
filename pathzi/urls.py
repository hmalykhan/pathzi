"""
URL configuration for pathzi project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path, include
from django.views.generic import RedirectView

from analytics.views import analytics_dashboard
from analytics.forms import StaffAuthenticationForm


urlpatterns = [
    path('', RedirectView.as_view(pattern_name='home', permanent=False)),
    path('dashboard/', analytics_dashboard, name='home'),
    path('login/', LoginView.as_view(
        template_name='analytics/login.html',
        authentication_form=StaffAuthenticationForm,
    ), name='login'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),
    path('admin/', admin.site.urls),
    path('auth/', include('rest_framework.urls', namespace = 'rest_framework')),
    path("api/billing/", include("billing.urls")),
    path('accounts/',include('accounts.urls')),
    path('qualifications/',include('qualification.urls')),
    path('courses/', include('courses.urls')),
    path('jobs/', include('jobs.urls')),
    path('apprenticeships/', include('apprenticeship.urls')),
    path('careers/', include('careers.urls')),
    path("geo/", include("geo_search.urls")),
    path("usage-limits/", include("usage_limits.urls")),
    path("analytics/", include("analytics.urls")),
]