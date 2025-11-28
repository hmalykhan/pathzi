from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.core.mail import send_mail
from django.conf import settings

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated, AllowAny

from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from rest_framework.response import Response

from .serializers import GoogleAuthSerializer

from .serializers import (
    UserSerializer,
    SignUpSerializer,
    LoginSerializer,
    ResetPasswordSerializer,
    ForgotPasswordSerializer,
    ForgotPasswordConfirmSerializer,
    UserDataSerializer,
    GoogleLoginResponseSerializer
)
import urllib.parse
import requests
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests


token_generator = PasswordResetTokenGenerator()


class UserAPI(APIView):
    def get(self, request):
        users = User.objects.all()
        serializer = UserSerializer(users, many=True)
        return Response(
            {
                "status": True,
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class SignUpAPI(APIView):
    def get(self, request):
        return Response(
            {"detail": "Send a POST request to create an account."},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = SignUpSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "status": False,
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        username = serializer.validated_data["username"]
        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]
        password2 = serializer.validated_data["password2"]

        # Check passwords match
        if password != password2:
            return Response(
                {
                    "status": False,
                    "message": "Passwords are not the same.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check username/email already taken
        if User.objects.filter(username=username).exists():
            return Response(
                {
                    "status": False,
                    "message": "Username already taken.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.filter(email=email).exists():
            return Response(
                {
                    "status": False,
                    "message": "Email already registered.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
        )

        # Optional: create token on signup
        token, _ = Token.objects.get_or_create(user=user)

        return Response(
            {
                "status": True,
                "message": "User created successfully.",
                "data": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "token": token.key,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class LoginAPI(APIView):
    """
    POST /login/
    Body: { "email": "...", "password": "..." }
    Returns: token if credentials are valid
    """

    def get(self, request):
        # Optional: so GET /login/ doesn't 405
        return Response(
            {"detail": "Send a POST request to log in."},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "status": False,
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        # Find user by email
        try:
            user_obj = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {
                    "status": False,
                    "message": "Invalid credentials.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Authenticate using username + password
        user = authenticate(username=user_obj.username, password=password)
        if not user:
            return Response(
                {
                    "status": False,
                    "message": "Invalid credentials.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get or create token
        token, _ = Token.objects.get_or_create(user=user)

        return Response(
            {
                "status": True,
                "data": {
                    "token": token.key,
                },
            },
            status=status.HTTP_200_OK,
        )
    
class ResetPasswordAPI(APIView):
    """
    POST /reset-password/
    Headers: Authorization: Token <token>
    Body: { "old_password": "...", "new_password": "...", "new_password2": "..." }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "status": False,
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_password = serializer.validated_data["old_password"]
        new_password = serializer.validated_data["new_password"]
        new_password2 = serializer.validated_data["new_password2"]

        user = request.user

        # Check old password
        if not user.check_password(old_password):
            return Response(
                {
                    "status": False,
                    "message": "Old password is incorrect.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check new passwords match
        if new_password != new_password2:
            return Response(
                {
                    "status": False,
                    "message": "New passwords do not match.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Set new password
        user.set_password(new_password)
        user.save()

        # Optional: invalidate old tokens and issue a new one
        Token.objects.filter(user=user).delete()
        new_token = Token.objects.create(user=user)

        return Response(
            {
                "status": True,
                "message": "Password changed successfully.",
                "data": {
                    "token": new_token.key,
                },
            },
            status=status.HTTP_200_OK,
        )

class ForgotPasswordAPI(APIView):
    """
    POST /forgot-password/
    Body: { "email": "user@example.com" }
    """

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"status": False, "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = serializer.validated_data["email"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Do not reveal whether the email exists (security best practice)
            return Response(
                {
                    "status": True,
                    "message": "email does not match.",
                },
                status=status.HTTP_200_OK,
            )

        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = token_generator.make_token(user)

        reset_link = request.build_absolute_uri(
            f"/password-reset-confirm/?uid={uidb64}&token={token}"
        )

        # Send email (you must configure EMAIL_BACKEND & DEFAULT_FROM_EMAIL)
        send_mail(
            subject="Password reset",
            message=f"Click the link to reset your password: {reset_link}",
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com"),
            recipient_list=[user.email],
            fail_silently=False,  # set False while debugging if you want errors
        )

        return Response(
            {
                "status": True,
                "message": "If this email is registered, a reset link has been sent.",
            },
            status=status.HTTP_200_OK,
        )


class ForgotPasswordConfirmAPI(APIView):
    """
    POST /forgot-password-confirm/
    Body: {
      "uidb64": "<uid from email>",
      "token": "<token from email>",
      "new_password": "...",
      "new_password2": "..."
    }
    """

    def post(self, request):
        serializer = ForgotPasswordConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"status": False, "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uidb64 = serializer.validated_data["uidb64"]
        token = serializer.validated_data["token"]
        new_password = serializer.validated_data["new_password"]
        new_password2 = serializer.validated_data["new_password2"]

        if new_password != new_password2:
            return Response(
                {"status": False, "message": "Passwords do not match."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Decode user id
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except Exception:
            return Response(
                {"status": False, "message": "Invalid reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check token
        if not token_generator.check_token(user, token):
            return Response(
                {"status": False, "message": "Invalid or expired token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Set new password
        user.set_password(new_password)
        user.save()

        # Optional: delete old tokens and issue a new one
        Token.objects.filter(user=user).delete()
        new_token = Token.objects.create(user=user)

        return Response(
            {
                "status": True,
                "message": "Password reset successfully.",
                "data": {
                    "token": new_token.key,
                },
            },
            status=status.HTTP_200_OK,
        )
    
class GoogleLoginAPI(APIView):
    """
    POST /auth/google/
    Body: { "id_token": "<google_id_token_here>" }

    Returns: DRF auth token + basic user info.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"status": False, "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        id_token_str = serializer.validated_data["id_token"]

        try:
            # Verify the token with Google
            idinfo = google_id_token.verify_oauth2_token(
                id_token_str,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID,
            )
        except Exception as e:
            return Response(
                {
                    "status": False,
                    "message": "Invalid Google token",
                    "detail": str(e),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # At this point token is valid
        # idinfo contains things like: sub, email, name, picture, etc.
        email = idinfo.get("email")
        email_verified = idinfo.get("email_verified", False)
        name = idinfo.get("name", "")
        google_user_id = idinfo.get("sub")  # Google's unique user ID

        if not email or not email_verified:
            return Response(
                {
                    "status": False,
                    "message": "Google account email is not verified.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get or create user in Django
        username = email.split("@")[0]

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": username,
                "first_name": name,
            },
        )

        # Optionally update name on each login
        if not created and name and user.first_name != name:
            user.first_name = name
            user.save()

        # Create or get DRF token
        token, _ = Token.objects.get_or_create(user=user)

        return Response(
            {
                "status": True,
                "message": "Google login successful.",
                "data": {
                    "token": token.key,
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "name": user.first_name,
                    },
                },
            },
            status=status.HTTP_200_OK,
        )

class GoogleAuthURLAPI(APIView):
    """
    GET /auth/google/url/
    Returns the Google OAuth URL as JSON.
    """

    def get(self, request):
        google_auth_base = "https://accounts.google.com/o/oauth2/v2/auth"

        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "consent",
        }

        auth_url = f"{google_auth_base}?{urllib.parse.urlencode(params)}"

        # No serializer needed here unless you want one.
        return Response({
            "status": True,
            "auth_url": auth_url
        }, status=status.HTTP_200_OK)


# -------------------------------------------------------
# STEP 2 — GOOGLE CALLBACK URL
# -------------------------------------------------------
class GoogleCallbackAPI(APIView):
    """
    GET /auth/google/callback/?code=XXXX
    Redirect handler → exchange code → verify → return JSON user + token
    """

    def get(self, request):
        code = request.GET.get("code")

        if not code:
            return Response({
                "status": False,
                "message": "Missing 'code' in callback URL."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Exchange "code" for Google tokens
        token_url = "https://oauth2.googleapis.com/token"

        data = {
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }

        token_res = requests.post(token_url, data=data)
        token_json = token_res.json()

        if "id_token" not in token_json:
            return Response({
                "status": False,
                "message": "Failed to exchange code for tokens.",
                "detail": token_json
            }, status=status.HTTP_400_BAD_REQUEST)

        id_token_str = token_json["id_token"]

        # Verify the ID token
        try:
            idinfo = google_id_token.verify_oauth2_token(
                id_token_str,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID
            )
        except Exception as e:
            return Response({
                "status": False,
                "message": "Invalid ID token.",
                "detail": str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

        # Extract user info
        email = idinfo.get("email")
        name = idinfo.get("name", "")
        username = email.split("@")[0]

        # Create user if not exist
        user, created = User.objects.get_or_create(
            email=email,
            defaults={"username": username, "first_name": name}
        )

        # Create/return DRF token
        token, _ = Token.objects.get_or_create(user=user)

        # Prepare data for serializer
        response_data = {
            "status": True,
            "message": "Google login successful.",
            "token": token.key,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "name": user.first_name,
            }
        }

        # Validate & serialize output
        serializer = GoogleLoginResponseSerializer(response_data)

        return Response(serializer.data, status=status.HTTP_200_OK)