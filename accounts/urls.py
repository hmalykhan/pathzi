from django.urls import path
from qualification.views import QualificationVeiw
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
                            HomeAPI,
                            GoogleMobileAuthAPI,
                            Otp_Checker,
                            AppleMobileAuthAPI,
                            AppleAuthURLAPI,
                            AppleCallbackAPI,
                            CurrentUserProfileLightAPI
                            )
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from .views import (
    CurrentUserCoordinatesListCreateAPI,
    CurrentUserCoordinateDetailAPI,
)

urlpatterns = [
path('users/',UserAPI.as_view()),
path('signup/',SignUpAPI.as_view()),
path('login/',LoginAPI.as_view()),

path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),

path("reset_password/", ResetPasswordAPI.as_view(), name="reset_password"),
path("forgot_password/", ForgotPasswordAPI.as_view(), name="forgot_password"),
path("forgot_password_confirmation/", ForgotPasswordConfirmationOTP.as_view()),
path("otp_check/",Otp_Checker.as_view() ),

path("user_profile/", CurrentUserProfileAPI.as_view(), name="user_profile"),
path("user_profile/light/", CurrentUserProfileLightAPI.as_view()),
path("coordinates/", CurrentUserCoordinatesListCreateAPI.as_view(), name="my-coordinates"),
path("coordinates/<int:pk>/", CurrentUserCoordinateDetailAPI.as_view(), name="my-coordinate-detail"),


path("auth/google/", GoogleMobileAuthAPI.as_view(), name="google_mobile_auth"),
path("auth/apple/", AppleMobileAuthAPI.as_view(), name="apple_mobile_auth"),

# keep this if this app has browser app.
path("google/auth/url/", GoogleAuthURLAPI.as_view(), name="google_auth_url"),
# path("apigoogle/callback/", GoogleCallbackAPI.as_view(), name="google_auth_callback"),
path("auth/google/callback/", GoogleCallbackAPI.as_view(), name="google_auth_callback"),
path("apple/auth/url/", AppleAuthURLAPI.as_view()),
path("auth/apple/callback/", AppleCallbackAPI.as_view()),

path("auth/password/set/request-otp/", SetPasswordGoogleAuthAPI.as_view(), name="google_auth_set_password"),
path("auth/password/set/confirm/", SetPasswordConfirmationGoogleAuthOTP.as_view()),

path("<int:pk>/create_qualification",QualificationVeiw.as_view({'post' : 'create_qualification'})),
]