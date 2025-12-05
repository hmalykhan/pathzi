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
                            HomeAPI
                            )
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

urlpatterns = [
path('users/',UserAPI.as_view()),
path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
path('signup/',SignUpAPI.as_view()),
path('login/',LoginAPI.as_view()),
path("reset_password/", ResetPasswordAPI.as_view(), name="reset_password"),
path("forgot_password/", ForgotPasswordAPI.as_view(), name="forgot_password"),
path("forgot_password_confirmation/", ForgotPasswordConfirmationOTP.as_view()),
path("google/auth/url/", GoogleAuthURLAPI.as_view(), name="google_auth_url"),
path("apigoogle/callback/", GoogleCallbackAPI.as_view(), name="google_auth_callback"),
path("user_profile/", CurrentUserProfileAPI.as_view(), name="user_profile"),
path("google_auth/set_password/", SetPasswordGoogleAuthAPI.as_view(), name="google_auth_set_password"),
path("<int:pk>/create_qualification",QualificationVeiw.as_view({'post' : 'create_qualification'})),
path("google_auth/set_password_confirmation/", SetPasswordConfirmationGoogleAuthOTP.as_view()),
]