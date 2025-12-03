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
from django.urls import path, include
from accounts.views import (
                            UserAPI,
                            LoginAPI,
                            SignUpAPI,
                            ResetPasswordAPI,
                            ForgotPasswordAPI,
                            ForgotPasswordConfirmationOTP,
                            GoogleAuthURLAPI,
                            GoogleCallbackAPI,
                            SetPasswordGoogleAuthAPI,
                            CurrentUserProfileAPI,
                            SetPasswordConfirmationGoogleAuthOTP,
                            HomeAPI
                            )

urlpatterns = [
    path('admin/', admin.site.urls),
    path('auth/', include('rest_framework.urls', namespace = 'rest_framework')),
    path('', HomeAPI.as_view()),
    path('users/',UserAPI.as_view()),
    path('signup/',SignUpAPI.as_view()),
    path('login/',LoginAPI.as_view()),
    path("reset_password/", ResetPasswordAPI.as_view(), name="reset_password"),
    path("forgot_password/", ForgotPasswordAPI.as_view(), name="forgot_password"),
    path("forgot_password_confirmation/", ForgotPasswordConfirmationOTP.as_view()),
    path("google/auth/url/", GoogleAuthURLAPI.as_view(), name="google_auth_url"),
    path("apigoogle/callback/", GoogleCallbackAPI.as_view(), name="google_auth_callback"),
    path("user_profile/", CurrentUserProfileAPI.as_view(), name="user_profile"),
    path("google_auth/set_password/", SetPasswordGoogleAuthAPI.as_view(), name="google_auth_set_password"),
    path("google_auth/set_password_confirmation/", SetPasswordConfirmationGoogleAuthOTP.as_view()),
]
 