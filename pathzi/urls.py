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
from django.urls import path
from accounts.views import UserAPI, LoginAPI, SignUpAPI, ResetPasswordAPI, ForgotPasswordAPI, ResetPasswordWithOTP, GoogleAuthURLAPI, GoogleCallbackAPI

urlpatterns = [
    path('admin/', admin.site.urls),
    path('users/',UserAPI.as_view()),
    path('signup/',SignUpAPI.as_view()),
    path('login/',LoginAPI.as_view()),
    path("reset-password/", ResetPasswordAPI.as_view(), name="reset-password"),
    path("forgot-password/", ForgotPasswordAPI.as_view(), name="forgot-password"),
    path("reset-password-otp/", ResetPasswordWithOTP.as_view()),
    path("auth/google/url/", GoogleAuthURLAPI.as_view(), name="google-auth-url"),
    path("apigoogle/callback/", GoogleCallbackAPI.as_view(), name="google-auth-callback")
]
 