from django.contrib.auth.models import User
from django.shortcuts import redirect
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
import random

from .serializers import (
    UserSerializer,
    UserProfileSerializer,
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
from .models import PasswordResetOTP, UserProfile
from django.utils import timezone
from django.utils.crypto import get_random_string


token_generator = PasswordResetTokenGenerator()

class HomeAPI(APIView):
    def get(self, request):
        return Response(
            {
                "status": True,
                "message": "Pathzi server is running Successfully :)",
            },
            status=status.HTTP_200_OK,
        )


class UserAPI(APIView):
    def get(self, request):
        users = UserProfile.objects.all()
        serializer = UserProfileSerializer(users, many=True)
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

        UserProfile.objects.create(
            appuser=user,
            age=0,                # or any default
            career_switcher="",
            interest=""
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

class CurrentUserProfileAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Get or create profile for the logged in user
        profile, created = UserProfile.objects.get_or_create(appuser=request.user)
        serializer = UserProfileSerializer(profile)
        return Response(
            {
                "status": True,
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def put(self, request):
        # Full update: user must send all fields
        profile, created = UserProfile.objects.get_or_create(appuser=request.user)
        serializer = UserProfileSerializer(profile, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "status": True,
                    "message": "Profile updated successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        return Response(
            {
                "status": False,
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def patch(self, request):
        # Partial update: user can send only some fields
        profile, created = UserProfile.objects.get_or_create(appuser=request.user)
        serializer = UserProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "status": True,
                    "message": "Profile updated successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        return Response(
            {
                "status": False,
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
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
    def post(self, request):
        email = request.data.get("email")

        if not email:
            return Response({"status": False, "message": "Email required"}, status=400)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"status": True, "message": "OTP sent if email exists"}, status=200)

        # Generate 6-digit OTP
        otp = str(random.randint(100000, 999999))

        # Save or update OTP record
        otp_record, created = PasswordResetOTP.objects.get_or_create(user=user)
        otp_record.otp = otp
        otp_record.created_at = timezone.now()
        otp_record.save()

        # Send OTP via email
        send_mail(
            subject="Your Password Reset OTP",
            message=f"Your OTP is: {otp}\nThis OTP is valid for 5 minutes.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
        )

        return Response({"status": True, "message": "OTP sent successfully"}, status=200)
    
class SetPasswordGoogleAuthAPI(APIView):
    def post(self, request):       
        try:
            user = User.objects.get(email=request.user.email)
        except User.DoesNotExist:
            return Response({"status": True, "message": "OTP sent if email exists"}, status=200)

        # Generate 6-digit OTP
        otp = str(random.randint(100000, 999999))

        # Save or update OTP record
        otp_record, created = PasswordResetOTP.objects.get_or_create(user=user)
        otp_record.otp = otp
        otp_record.created_at = timezone.now()
        otp_record.save()

        # Send OTP via email
        send_mail(
            subject="Your Password Reset OTP",
            message=f"Your OTP is: {otp}\nThis OTP is valid for 5 minutes.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[request.user.email],
        )

        return Response({"status": True, "message": "OTP sent successfully"}, status=200)


class SetPasswordConfirmationGoogleAuthOTP(APIView):
    def post(self, request):
        otp = request.data.get("otp")
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        if not (otp and new_password and confirm_password):
            return Response({"status": False, "message": "Missing fields"}, status=400)
        
        if new_password != confirm_password:
            return Response({"status": False, "message": "Passwords does not match."}, status=400)

        try:
            user = User.objects.get(email=request.user.email)
        except User.DoesNotExist:
            return Response({"status": False, "message": "Invalid email"}, status=400)

        try:
            otp_record = PasswordResetOTP.objects.get(user=user)
        except PasswordResetOTP.DoesNotExist:
            return Response({"status": False, "message": "OTP not requested"}, status=400)

        if not otp_record.is_valid():
            return Response({"status": False, "message": "OTP expired"}, status=400)

        if otp_record.otp != otp:
            return Response({"status": False, "message": "Incorrect OTP"}, status=400)

        # Reset password
        user.set_password(new_password)
        user.save()

        # Delete OTP after successful reset
        otp_record.delete()

        return Response({"status": True, "message": "Password reset successful"})
    
class ForgotPasswordConfirmationOTP(APIView):
        def post(self, request):
            email = request.data.get("email")
            otp = request.data.get("otp")
            new_password = request.data.get("new_password")
            confirm_password = request.data.get("confirm_password")

            if not (email and otp and new_password and confirm_password):
                return Response({"status": False, "message": "Missing fields"}, status=400)
            
            if new_password != confirm_password:
                return Response({"status": False, "message": "Passwords does not match."}, status=400)

            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response({"status": False, "message": "Invalid email"}, status=400)

            try:
                otp_record = PasswordResetOTP.objects.get(user=user)
            except PasswordResetOTP.DoesNotExist:
                return Response({"status": False, "message": "OTP not requested"}, status=400)

            if not otp_record.is_valid():
                return Response({"status": False, "message": "OTP expired"}, status=400)

            if otp_record.otp != otp:
                return Response({"status": False, "message": "Incorrect OTP"}, status=400)

            # Reset password
            user.set_password(new_password)
            user.save()

            # Delete OTP after successful reset
            otp_record.delete()

            return Response({"status": True, "message": "Password reset successful"})
    
    

class GoogleAuthURLAPI(APIView):
    """
    GET /auth/google/url/
    Automatically redirect user to Google login page.
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

        return redirect(auth_url)


# -------------------------------------------------------
# STEP 2 — GOOGLE CALLBACK URL
# -------------------------------------------------------
class GoogleCallbackAPI(APIView):
    """
    GET /auth/google/callback/?code=XXXX
    Handles Google OAuth callback → verifies token → creates user → sets random password → returns token + user data
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

        # Extract user info from Google
        email = idinfo.get("email")
        first_name = idinfo.get("given_name", "")
        last_name = idinfo.get("family_name", "")
        username = email.split("@")[0]

        # Create user if not exists
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
            }
        )

        # If it's a new user, set a random password and create profile
        if created:
            # 🔐 Generate a random password (not returned to client)
            random_password = get_random_string(length=12)
            user.set_password(random_password)
            user.save()

            UserProfile.objects.create(
                appuser=user,
                age=0,
                career_switcher="",
                interest=""
            )

        # Create or get auth token
        token, _ = Token.objects.get_or_create(user=user)

        # Prepare response structure
        response_data = {
            "status": True,
            "message": "Google login successful.",
            "token": token.key,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "name": user.get_full_name(),
                "first_name": user.first_name,
                "last_name": user.last_name,
            }
        }

        # Serialize response
        serializer = GoogleLoginResponseSerializer(response_data)

        return Response(serializer.data, status=status.HTTP_200_OK)

