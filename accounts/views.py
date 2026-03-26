import logging
import random
import urllib.parse
import requests
import threading
from django.db import transaction

from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.crypto import get_random_string

from asgiref.sync import sync_to_async

from rest_framework import status, generics, permissions
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import CoordinatesSerializer

from .models import PasswordResetOTP, UserProfile, Coordinates
from .serializers import (
    UserSerializer,
    UserProfileSerializer,
    SignUpSerializer,
    LoginSerializer,
    ResetPasswordSerializer,
    ForgotPasswordSerializer,
    ForgotPasswordConfirmSerializer,
    GoogleLoginResponseSerializer,
)

logger = logging.getLogger(__name__)


import jwt
import requests
from django.conf import settings
# from logging import logger
import requests
from rest_framework_simplejwt.tokens import RefreshToken
from asgiref.sync import sync_to_async
from django.utils.crypto import get_random_string
from django.contrib.auth.models import User
from rest_framework.views import APIView
from rest_framework import status, permissions
import threading
from django.core.mail import send_mail


def send_email_async(subject, message, from_email, recipient_list):
    def send():
        send_mail(
            subject,
            message,
            from_email,
            recipient_list,
            fail_silently=False,
        )

    thread = threading.Thread(target=send)
    thread.start()



APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"
CACHE_KEY = "apple_public_keys"
CACHE_TIMEOUT = 60 * 60  # 1 hour


# 🔐 Get Apple public keys (cached)
def get_apple_keys():
    keys = cache.get(CACHE_KEY)
    if keys:
        return keys

    res = requests.get(APPLE_KEYS_URL, timeout=10)
    res.raise_for_status()

    keys = res.json().get("keys", [])
    cache.set(CACHE_KEY, keys, CACHE_TIMEOUT)
    return keys


def get_public_key(kid):
    keys = get_apple_keys()
    key = next((k for k in keys if k.get("kid") == kid), None)

    if not key:
        cache.delete(CACHE_KEY)
        keys = get_apple_keys()
        key = next((k for k in keys if k.get("kid") == kid), None)

    if not key:
        raise ValueError("Apple public key not found")

    return jwt.algorithms.RSAAlgorithm.from_jwk(key)


# 🔐 Verify Apple token
def verify_apple_token(identity_token):
    header = jwt.get_unverified_header(identity_token)

    if header.get("alg") != "RS256":
        raise ValueError("Invalid algorithm")

    public_key = get_public_key(header.get("kid"))

    decoded = jwt.decode(
        identity_token,
        public_key,
        algorithms=["RS256"],
        audience=settings.APPLE_CLIENT_ID,
        issuer=APPLE_ISSUER,
    )

    return decoded


class AppleMobileAuthAPI(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        identity_token = request.data.get("identity_token")

        if not identity_token:
            return Response(
                {"status": False, "message": "Missing identity_token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            data = verify_apple_token(identity_token)
        except Exception as e:
            logger.exception("AppleAuth invalid token: %s", str(e))
            return Response(
                {"status": False, "message": "Invalid Apple token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        apple_sub = (data.get("sub") or "").strip()
        email = (data.get("email") or "").strip().lower()

        if not apple_sub:
            return Response(
                {"status": False, "message": "Invalid Apple token data"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # fallback email
        email = email or f"{apple_sub}@apple.local"
        username = email.split("@")[0]

        try:
            with transaction.atomic():

                # ✅ 1. Find by apple_sub
                profile = UserProfile.objects.select_related("appuser").filter(
                    apple_sub=apple_sub
                ).first()

                if profile:
                    user = profile.appuser
                    created = False

                else:
                    # ✅ 2. Fallback by email
                    user = User.objects.filter(email=email).first()

                    if not user:
                        user = User.objects.create(
                            username=username,
                            email=email,
                        )
                        user.set_password(get_random_string(20))
                        user.save(update_fields=["password"])
                        created = True
                    else:
                        created = False

                    # ✅ 3. Attach apple_sub
                    profile, _ = UserProfile.objects.get_or_create(appuser=user)

                    if not profile.apple_sub:
                        profile.apple_sub = apple_sub
                        profile.save(update_fields=["apple_sub"])

                # ensure profile exists
                UserProfile.objects.get_or_create(appuser=user)

                refresh = RefreshToken.for_user(user)

        except Exception as e:
            logger.exception("AppleAuth DB error: %s", str(e))
            return Response(
                {"status": False, "message": "Login failed, please try again"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        logger.info(
            "AppleAuth success: user_id=%s email=%s created=%s",
            user.id,
            user.email,
            created,
        )

        return Response(
            {
                "status": True,
                "message": "Apple login successful",
                "data": {
                    "token": {
                        "refresh": str(refresh),
                        "access": str(refresh.access_token),
                    },
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "name": user.get_full_name(),
                    },
                },
            },
            status=status.HTTP_200_OK,
        )


class HomeAPI(APIView):
    def get(self, request):
        logger.info("HomeAPI hit")
        return Response(
            {"status": True, "message": "Pathzi server is running Successfully :)"},
            status=status.HTTP_200_OK,
        )


class UserAPI(generics.ListAPIView):
    """
    GET /users/
    """
    queryset = UserProfile.objects.select_related("appuser").all()
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]


class SignUpAPI(generics.CreateAPIView):
    """
    POST /auth/register/
    Body handled by SignUpSerializer.
    """
    serializer_class = SignUpSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            errors = serializer.errors

            if "email" in errors and errors["email"]:
                msg = errors["email"][0]
            elif "username" in errors and errors["username"]:
                msg = errors["username"][0]
            elif "password2" in errors and errors["password2"]:
                msg = errors["password2"][0]
            elif "password" in errors and errors["password"]:
                msg = errors["password"][0]
            elif "non_field_errors" in errors and errors["non_field_errors"]:
                msg = errors["non_field_errors"][0]
            else:
                first_key = next(iter(errors), None)
                if first_key is None:
                    msg = "Invalid data."
                else:
                    val = errors[first_key]
                    msg = val[0] if isinstance(val, list) and val else str(val)

            logger.warning("Signup validation failed: %s", str(msg))
            return Response(
                {"status": False, "message": str(msg)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        email = (data.get("email") or "").strip().lower()
        username = data["username"]

        # Check uniqueness with optimized queries (will use indexes)
        if User.objects.filter(username=username).exists():
            logger.warning("Signup failed: username already taken username=%s", username)
            return Response(
                {"status": False, "message": "Username already taken."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.filter(email__iexact=email).exists():
            logger.warning("Signup failed: email already registered email=%s", email)
            return Response(
                {"status": False, "message": "Email already registered."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=data["password"],
            )
            # Use create instead of get_or_create since we know user is new
            UserProfile.objects.create(appuser=user, age=0)
        except Exception as e:
            logger.exception("Signup failed (server error): %s", str(e))
            return Response(
                {"status": False, "message": "Could not create user. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        refresh = RefreshToken.for_user(user)

        logger.info("User created successfully: user_id=%s email=%s", user.id, user.email)
        return Response(
            {
                "status": True,
                "message": "User created successfully.",
                "data": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "token": {
                        "refresh": str(refresh),
                        "access": str(refresh.access_token),
                    },
                },
            },
            status=status.HTTP_201_CREATED,
        )




def _sync_profile_from_coordinate(profile: UserProfile, coord: Coordinates) -> None:
    """
    Copy active coordinate location into UserProfile (only updates non-empty values).
    Since Coordinates doesn't have an address field, we build a simple address string.
    """
    update_fields = []

    if coord.city:
        profile.city = coord.city
        update_fields.append("city")

    if coord.postal_code:
        profile.zip_code = coord.postal_code
        update_fields.append("zip_code")

    # Build a simple address string: "City, State, Postcode"
    parts = [p for p in [coord.city, coord.state, coord.postal_code] if p]
    if parts:
        profile.address = ", ".join(parts)
        update_fields.append("address")

    if coord.latitude is not None:
        profile.lat = coord.latitude
        update_fields.append("lat")

    if coord.longitude is not None:
        profile.lng = coord.longitude
        update_fields.append("lng")

    if update_fields:
        profile.save(update_fields=list(set(update_fields)))


def _set_only_one_active(profile: UserProfile, active_coord_id: int) -> None:
    """
    Ensures only one coordinate is active for this profile.
    """
    Coordinates.objects.filter(user_profile=profile).exclude(id=active_coord_id).update(active=False)


class CurrentUserProfileAPI(generics.RetrieveUpdateAPIView):
    """
    GET /accounts/user_profile/
    PUT /accounts/user_profile/
    PATCH /accounts/user_profile/
    """
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        profile, _ = UserProfile.objects.get_or_create(appuser=self.request.user)
        return profile

    def patch(self, request, *args, **kwargs):
        profile, _ = UserProfile.objects.get_or_create(appuser=request.user)
        serializer = self.get_serializer(profile, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            logger.info("Profile updated: user_id=%s", request.user.id)
            return Response(
                {"status": True, "message": "Profile updated successfully.", "data": serializer.data},
                status=status.HTTP_200_OK,
            )

        errors = serializer.errors
        if "non_field_errors" in errors and errors["non_field_errors"]:
            msg = errors["non_field_errors"][0]
        else:
            first_key = next(iter(errors), None)
            if first_key:
                val = errors[first_key]
                msg = val[0] if isinstance(val, list) and val else str(val)
            else:
                msg = "Invalid data."

        logger.warning("Profile update validation failed: user_id=%s msg=%s", request.user.id, str(msg))
        return Response({"status": False, "message": str(msg)}, status=status.HTTP_400_BAD_REQUEST)


class CurrentUserCoordinatesListCreateAPI(generics.ListCreateAPIView):
    """
    GET  /accounts/coordinates/        -> list my coordinates
    POST /accounts/coordinates/        -> create new coordinate for me

    ✅ NEW behavior:
    - If created coordinate is active=True (default), deactivate others + sync UserProfile.
    """
    serializer_class = CoordinatesSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_user_profile(self):
        profile, _ = UserProfile.objects.get_or_create(appuser=self.request.user)
        return profile

    def get_queryset(self):
        profile = self.get_user_profile()
        return Coordinates.objects.filter(user_profile=profile).order_by("-id")

    @transaction.atomic
    def perform_create(self, serializer):
        profile = self.get_user_profile()
        coord = serializer.save(user_profile=profile)

        # if it is active, make others inactive + sync profile
        if coord.active:
            _set_only_one_active(profile, coord.id)
            _sync_profile_from_coordinate(profile, coord)

    def create(self, request, *args, **kwargs):
        resp = super().create(request, *args, **kwargs)
        return Response(
            {"status": True, "message": "Coordinate created successfully.", "data": resp.data},
            status=resp.status_code,
        )


class CurrentUserCoordinateDetailAPI(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /accounts/coordinates/<id>/
    PATCH  /accounts/coordinates/<id>/
    PUT    /accounts/coordinates/<id>/
    DELETE /accounts/coordinates/<id>/

    ✅ NEW behavior:
    - When coordinate becomes active=True (or is already active), deactivate others
    - Sync UserProfile city/zip/address/lat/lng from this active coordinate
    """
    serializer_class = CoordinatesSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "pk"

    def get_user_profile(self):
        profile, _ = UserProfile.objects.get_or_create(appuser=self.request.user)
        return profile

    def get_queryset(self):
        profile = self.get_user_profile()
        return Coordinates.objects.filter(user_profile=profile)

    @transaction.atomic
    def perform_update(self, serializer):
        profile = self.get_user_profile()
        coord = serializer.save()

        # If this coord is active (either toggled now or already active), enforce one-active + sync profile
        if coord.active:
            _set_only_one_active(profile, coord.id)
            _sync_profile_from_coordinate(profile, coord)

    @transaction.atomic
    def perform_destroy(self, instance):
        profile = self.get_user_profile()
        was_active = bool(instance.active)

        instance.delete()

        # If the deleted one was active, choose a fallback active coordinate (latest)
        if was_active:
            fallback = Coordinates.objects.filter(user_profile=profile).order_by("-id").first()
            if fallback:
                fallback.active = True
                fallback.save(update_fields=["active"])
                _set_only_one_active(profile, fallback.id)
                _sync_profile_from_coordinate(profile, fallback)
            else:
                # no coordinates left -> optionally clear profile location
                profile.city = ""
                profile.zip_code = ""
                profile.address = ""
                profile.lat = None
                profile.lng = None
                profile.save(update_fields=["city", "zip_code", "address", "lat", "lng"])

    def patch(self, request, *args, **kwargs):
        resp = super().patch(request, *args, **kwargs)
        if resp.status_code < 400:
            return Response(
                {"status": True, "message": "Coordinate updated successfully.", "data": resp.data},
                status=resp.status_code,
            )
        return resp

    def put(self, request, *args, **kwargs):
        resp = super().put(request, *args, **kwargs)
        if resp.status_code < 400:
            return Response(
                {"status": True, "message": "Coordinate updated successfully.", "data": resp.data},
                status=resp.status_code,
            )
        return resp

    def delete(self, request, *args, **kwargs):
        super().delete(request, *args, **kwargs)
        return Response(
            {"status": True, "message": "Coordinate deleted successfully."},
            status=status.HTTP_200_OK,
        )
class LoginAPI(APIView):
    """
    POST /login/
    Body: { "email": "...", "password": "..." }
    Returns: token if credentials are valid
    """

    def get(self, request):
        return Response(
            {"status": True, "message": "Send a POST request to log in."},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            if "email" in errors and errors["email"]:
                msg = errors["email"][0]
            elif "password" in errors and errors["password"]:
                msg = errors["password"][0]
            elif "non_field_errors" in errors and errors["non_field_errors"]:
                msg = errors["non_field_errors"][0]
            else:
                first_key = next(iter(errors), None)
                if first_key:
                    val = errors[first_key]
                    msg = val[0] if isinstance(val, list) and val else str(val)
                else:
                    msg = "Invalid data."

            logger.warning("Login validation failed: %s", str(msg))
            return Response(
                {"status": False, "message": str(msg)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = (serializer.validated_data.get("email") or "").strip().lower()
        password = serializer.validated_data["password"]

        # Use filter().first() for better performance with index
        user_obj = User.objects.filter(email__iexact=email).first()
        if not user_obj:
            logger.warning("Login failed: user not found for email=%s", email)
            return Response(
                {"status": False, "message": "Invalid credentials."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(username=user_obj.username, password=password)
        if not user:
            logger.warning("Login failed: invalid password for email=%s", email)
            return Response(
                {"status": False, "message": "Invalid credentials."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        refresh = RefreshToken.for_user(user)
        logger.info("Login success: user_id=%s email=%s", user.id, user.email)

        return Response(
            {
                "status": True,
                "message": "Login successful.",
                "data": {
                    "token": {
                        "refresh": str(refresh),
                        "access": str(refresh.access_token),
                    }
                },
            },
            status=status.HTTP_200_OK,
        )


class ResetPasswordAPI(APIView):
    """
    POST /reset-password/
    Headers: Authorization: Bearer <access>
    Body: { "old_password": "...", "new_password": "...", "new_password2": "..." }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)

        if not serializer.is_valid():
            errors = serializer.errors
            if "old_password" in errors and errors["old_password"]:
                msg = errors["old_password"][0]
            elif "new_password" in errors and errors["new_password"]:
                msg = errors["new_password"][0]
            elif "new_password2" in errors and errors["new_password2"]:
                msg = errors["new_password2"][0]
            elif "non_field_errors" in errors and errors["non_field_errors"]:
                msg = errors["non_field_errors"][0]
            else:
                first_key = next(iter(errors), None)
                if first_key:
                    val = errors[first_key]
                    msg = val[0] if isinstance(val, list) and val else str(val)
                else:
                    msg = "Invalid data."

            logger.warning("ResetPassword validation failed: user_id=%s msg=%s", request.user.id, str(msg))
            return Response(
                {"status": False, "message": str(msg)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_password = serializer.validated_data["old_password"]
        new_password = serializer.validated_data["new_password"]
        new_password2 = serializer.validated_data["new_password2"]

        user = request.user

        if not user.check_password(old_password):
            logger.warning("ResetPassword failed: old password incorrect user_id=%s", user.id)
            return Response(
                {"status": False, "message": "Old password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_password != new_password2:
            return Response(
                {"status": False, "message": "New passwords do not match."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save()

        refresh = RefreshToken.for_user(user)
        logger.info("Password changed successfully: user_id=%s", user.id)

        return Response(
            {
                "status": True,
                "message": "Password changed successfully.",
                "data": {
                    "token": {
                        "refresh": str(refresh),
                        "access": str(refresh.access_token),
                    }
                },
            },
            status=status.HTTP_200_OK,
        )


class ForgotPasswordAPI(APIView):
    """
    POST /accounts/forgot_password/
    Body: { "email": "..." }
    Sends OTP to email (if exists).
    """

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()

        if not email:
            logger.warning("ForgotPassword: missing email in request")
            return Response(
                {"status": False, "message": "Email required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Use filter().first() for better performance with index
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            # Don't reveal whether user exists
            logger.info("ForgotPassword requested for non-existing email=%s", email)
            return Response(
                # {"status": False, "message": "OTP sent if email exists"},
                {"status": False, "message": "email does not exist."},
                status=status.HTTP_200_OK,
            )

        otp = str(random.randint(100000, 999999))

        try:
            otp_record, _ = PasswordResetOTP.objects.get_or_create(user=user)
            otp_record.otp = otp
            otp_record.created_at = timezone.now()
            otp_record.save()
        except Exception as e:
            logger.exception(
                "ForgotPassword: failed saving OTP record user_id=%s email=%s err=%s",
                user.id, email, str(e)
            )
            return Response(
                {"status": False, "message": "Could not generate OTP. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Send email in background thread - doesn't block the response
        send_email_async(
            subject="Your Password Reset OTP",
            message=f"Your OTP is: {otp}\nThis OTP is valid for 5 minutes.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
        )

        logger.info("ForgotPassword OTP sent: user_id=%s email=%s", user.id, email)

        # ✅ Recommended: DO NOT return JWT tokens here (OTP not verified yet)
        return Response(
            {"status": True, "message": "OTP sent successfully"},
            status=status.HTTP_200_OK,
        )



class SetPasswordGoogleAuthAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = User.objects.get(email=request.user.email)
        except User.DoesNotExist:
            logger.warning(
                "SetPasswordGoogleAuthAPI: user not found for request.user email=%s",
                request.user.email,
            )
            return Response(
                {"status": False, "message": "Invalid user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp = str(random.randint(100000, 999999))

        try:
            otp_record, _ = PasswordResetOTP.objects.get_or_create(user=user)
            otp_record.otp = otp
            otp_record.created_at = timezone.now()
            otp_record.save()
        except Exception as e:
            logger.exception(
                "SetPasswordGoogleAuthAPI: failed saving OTP user_id=%s err=%s",
                user.id, str(e)
            )
            return Response(
                {"status": False, "message": "Could not generate OTP. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Send email in background thread - doesn't block the response
        send_email_async(
            subject="Your Password Reset OTP",
            message=f"Your OTP is: {otp}\nThis OTP is valid for 5 minutes.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[request.user.email],
        )

        logger.info("SetPasswordGoogleAuth OTP sent: user_id=%s email=%s", user.id, request.user.email)
        return Response(
            {"status": True, "message": "OTP sent successfully"},
            status=status.HTTP_200_OK,
        )



class SetPasswordConfirmationGoogleAuthOTP(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        otp = (request.data.get("otp") or "").strip()
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        if not (otp and new_password and confirm_password):
            return Response({"status": False, "message": "Missing fields"}, status=status.HTTP_400_BAD_REQUEST)

        if new_password != confirm_password:
            return Response({"status": False, "message": "Passwords does not match."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=request.user.email)
        except User.DoesNotExist:
            return Response({"status": False, "message": "Invalid email"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            otp_record = PasswordResetOTP.objects.get(user=user)
        except PasswordResetOTP.DoesNotExist:
            return Response({"status": False, "message": "OTP not requested"}, status=status.HTTP_400_BAD_REQUEST)

        if not otp_record.is_valid():
            return Response({"status": False, "message": "OTP expired"}, status=status.HTTP_400_BAD_REQUEST)

        if otp_record.otp != otp:
            return Response({"status": False, "message": "Incorrect OTP"}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save()
        otp_record.delete()

        logger.info("GoogleAuth password set: user_id=%s", user.id)
        return Response({"status": True, "message": "Password reset successful"}, status=status.HTTP_200_OK)


class Otp_Checker(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        otp = (request.data.get("otp") or "").strip()
        if not otp:
            return Response({"status": False, "message": "OTP required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            otp_record = PasswordResetOTP.objects.get(user=request.user)
        except PasswordResetOTP.DoesNotExist:
            return Response({"status": False, "message": "OTP not requested"}, status=status.HTTP_400_BAD_REQUEST)

        if not otp_record.is_valid():
            return Response({"status": False, "message": "OTP expired"}, status=status.HTTP_400_BAD_REQUEST)

        if otp_record.otp != otp:
            return Response({"status": False, "message": "Incorrect OTP"}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"status": True, "message": "Correct OTP"}, status=status.HTTP_200_OK)


class ForgotPasswordConfirmationOTP(APIView):
    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        otp = (request.data.get("otp") or "").strip()
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        if not (email and otp and new_password and confirm_password):
            return Response({"status": False, "message": "Missing fields"}, status=status.HTTP_400_BAD_REQUEST)

        if new_password != confirm_password:
            return Response({"status": False, "message": "Passwords does not match."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"status": False, "message": "Invalid email"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            otp_record = PasswordResetOTP.objects.get(user=user)
        except PasswordResetOTP.DoesNotExist:
            return Response({"status": False, "message": "OTP not requested"}, status=status.HTTP_400_BAD_REQUEST)

        if not otp_record.is_valid():
            return Response({"status": False, "message": "OTP expired"}, status=status.HTTP_400_BAD_REQUEST)

        if otp_record.otp != otp:
            return Response({"status": False, "message": "Incorrect OTP"}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save()
        otp_record.delete()

        logger.info("ForgotPassword OTP confirmed and password reset: user_id=%s email=%s", user.id, email)
        return Response({"status": True, "message": "Password reset successful"}, status=status.HTTP_200_OK)



class GoogleAuthURLAPI(APIView):
    def get(self, request):
        google_auth_base = "https://accounts.google.com/o/oauth2/v2/auth"

        params = {
            "client_id": settings.GOOGLE_WEB_CLIENT_ID,  # ✅ use web client
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "consent",
        }

        auth_url = f"{google_auth_base}?{urllib.parse.urlencode(params)}"
        return redirect(auth_url)


class GoogleCallbackAPI(APIView):
    def get(self, request):
        code = request.GET.get("code")

        if not code:
            return Response(
                {"status": False, "message": "Missing 'code'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token_url = "https://oauth2.googleapis.com/token"

        payload = {
            "code": code,
            "client_id": settings.GOOGLE_WEB_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }

        try:
            token_res = requests.post(token_url, data=payload)
            token_json = token_res.json()
        except Exception as e:
            return Response(
                {"status": False, "message": "Token exchange failed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        id_token_str = token_json.get("id_token")

        if not id_token_str:
            return Response(
                {"status": False, "message": "No id_token received"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ✅ Print for terminal testing
        print("\n===== GOOGLE ID TOKEN =====")
        print(id_token_str)
        print("===== END TOKEN =====\n")

        # ✅ Optional: decode without strict client check
        try:
            idinfo = google_id_token.verify_oauth2_token(
                id_token_str,
                google_requests.Request(),
            )
        except Exception:
            idinfo = {}

        # ✅ Return token in response for easy copy (TEST ONLY)
        return Response(
            {
                "status": True,
                "id_token": id_token_str,
                "decoded": {
                    "email": idinfo.get("email"),
                    "aud": idinfo.get("aud"),
                },
            },
            status=status.HTTP_200_OK,
        )

    
class GoogleMobileAuthAPI(APIView):
    """
    Flutter flow:
    - Flutter gets Google idToken using Google Sign-In SDK
    - Flutter sends it here
    - Backend verifies it and returns SimpleJWT tokens
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        id_token_str = request.data.get("id_token")
        if not id_token_str:
            return Response(
                {"status": False, "message": "Missing 'id_token'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            idinfo = google_id_token.verify_oauth2_token(
                id_token_str,
                google_requests.Request(),
            )

            client_ids = {
                settings.GOOGLE_WEB_CLIENT_ID,
                settings.GOOGLE_ANDROID_CLIENT_ID,
                settings.GOOGLE_IOS_CLIENT_ID,
            }
            client_ids = {cid for cid in client_ids if cid}

            if idinfo.get("aud") not in client_ids:
                raise ValueError("Invalid audience")

        except Exception as e:
            logger.exception("GoogleMobileAuth invalid token: %s", str(e))
            return Response(
                {"status": False, "message": "Invalid Google token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = (idinfo.get("email") or "").strip().lower()
        if not email:
            return Response(
                {"status": False, "message": "Google token missing email"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if idinfo.get("email_verified") is False:
            return Response(
                {"status": False, "message": "Google email is not verified"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        first_name = (idinfo.get("given_name") or "").strip()
        last_name = (idinfo.get("family_name") or "").strip()
        username = email.split("@")[0]

        try:
            with transaction.atomic():
                user, created = User.objects.get_or_create(
                    email=email,
                    defaults={
                        "username": username,
                        "first_name": first_name,
                        "last_name": last_name,
                    },
                )

                update_fields = []

                # Keep existing behavior, but safely fill missing fields
                if not user.username:
                    user.username = username
                    update_fields.append("username")

                # Safe sync with Google profile without changing response behavior
                if user.first_name != first_name:
                    user.first_name = first_name
                    update_fields.append("first_name")

                if user.last_name != last_name:
                    user.last_name = last_name
                    update_fields.append("last_name")

                if created:
                    user.set_password(get_random_string(20))
                    update_fields.append("password")

                if update_fields:
                    user.save(update_fields=update_fields)

                UserProfile.objects.get_or_create(
                    appuser=user,
                    defaults={"age": 0},
                )

                refresh = RefreshToken.for_user(user)

        except Exception as e:
            logger.exception("GoogleMobileAuth database error: %s", str(e))
            return Response(
                {"status": False, "message": "Login failed, please try again"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        logger.info(
            "GoogleMobileAuth success: user_id=%s email=%s",
            user.id,
            user.email,
        )

        return Response(
            {
                "status": True,
                "message": "Google login successful",
                "data": {
                    "token": {
                        "refresh": str(refresh),
                        "access": str(refresh.access_token),
                    },
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "name": user.get_full_name(),
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                    },
                },
            },
            status=status.HTTP_200_OK,
        )


# Old
# class GoogleAuthURLAPI(APIView):
#     """
#     GET /auth/google/url/
#     Redirect user to Google login page.
#     """

#     def get(self, request):
#         google_auth_base = "https://accounts.google.com/o/oauth2/v2/auth"
#         params = {
#             "client_id": settings.GOOGLE_CLIENT_ID,
#             "redirect_uri": settings.GOOGLE_REDIRECT_URI,
#             "response_type": "code",
#             "scope": "openid email profile",
#             "access_type": "offline",
#             "prompt": "consent",
#         }
#         auth_url = f"{google_auth_base}?{urllib.parse.urlencode(params)}"
#         logger.info("GoogleAuthURL redirect generated")
#         return redirect(auth_url)


# class GoogleCallbackAPI(APIView):
#     """
#     GET /auth/google/callback/?code=XXXX
#     Exchange code -> verify id_token -> create/fetch user -> return tokens
#     """

#     async def get(self, request):
#         code = request.GET.get("code")
#         if not code:
#             return Response(
#                 {"status": False, "message": "Missing 'code' in callback URL."},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         token_url = "https://oauth2.googleapis.com/token"
#         payload = {
#             "code": code,
#             "client_id": settings.GOOGLE_CLIENT_ID,
#             "client_secret": settings.GOOGLE_CLIENT_SECRET,
#             "redirect_uri": settings.GOOGLE_REDIRECT_URI,
#             "grant_type": "authorization_code",
#         }

#         try:
#             token_res = await sync_to_async(requests.post)(token_url, data=payload)
#             token_json = token_res.json()
#         except Exception as e:
#             logger.exception("GoogleCallback token exchange failed: %s", str(e))
#             return Response(
#                 {"status": False, "message": "Failed to exchange code for tokens."},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         id_token_str = token_json.get("id_token")
#         print("ID TOKEN:", id_token_str)
#         if not id_token_str:
#             logger.warning("GoogleCallback: missing id_token in response")
#             return Response(
#                 {"status": False, "message": "Failed to exchange code for tokens."},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         try:
#             idinfo = await sync_to_async(google_id_token.verify_oauth2_token)(
#                 id_token_str,
#                 google_requests.Request(),
#                 settings.GOOGLE_CLIENT_ID,
#             )
#         except Exception as e:
#             logger.exception("GoogleCallback: invalid ID token: %s", str(e))
#             return Response(
#                 {"status": False, "message": "Invalid ID token."},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         email = (idinfo.get("email") or "").strip().lower()
#         if not email:
#             return Response(
#                 {"status": False, "message": "Google token missing email."},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         first_name = idinfo.get("given_name", "") or ""
#         last_name = idinfo.get("family_name", "") or ""
#         username = email.split("@")[0]

#         user, created = await sync_to_async(User.objects.get_or_create, thread_sensitive=True)(
#             email=email,
#             defaults={
#                 "username": username,
#                 "first_name": first_name,
#                 "last_name": last_name,
#             },
#         )

#         if created:
#             # set random password for Django auth
#             random_password = get_random_string(length=12)
#             user.set_password(random_password)
#             await sync_to_async(user.save, thread_sensitive=True)()
#             await sync_to_async(UserProfile.objects.get_or_create, thread_sensitive=True)(appuser=user, defaults={"age": 0})

#         refresh = RefreshToken.for_user(user)

#         response_data = {
#             "status": True,
#             "message": "Google login successful.",
#             "token": {
#                 "refresh": str(refresh),
#                 "access": str(refresh.access_token),
#             },
#             "user": {
#                 "id": user.id,
#                 "username": user.username,
#                 "email": user.email,
#                 "name": user.get_full_name(),
#                 "first_name": user.first_name,
#                 "last_name": user.last_name,
#             },
#         }

#         # keep your serializer if you want, but don’t raise default error format
#         serializer = GoogleLoginResponseSerializer(data=response_data)
#         if not serializer.is_valid():
#             errors = serializer.errors
#             first_key = next(iter(errors), None)
#             if first_key:
#                 val = errors[first_key]
#                 msg = val[0] if isinstance(val, list) and val else str(val)
#             else:
#                 msg = "Invalid data."
#             logger.warning("GoogleCallback response serialization failed: %s", str(msg))
#             return Response(
#                 {"status": False, "message": "Google login failed."},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         logger.info("GoogleCallback success: user_id=%s email=%s", user.id, user.email)
#         return Response(serializer.data, status=status.HTTP_200_OK)

# Old
# class GoogleMobileAuthAPI(APIView):
#     """
#     Flutter flow:
#     - Flutter gets Google idToken using Google Sign-In SDK
#     - Flutter sends it here
#     - Backend verifies it and returns SimpleJWT tokens
#     """
#     permission_classes = [permissions.AllowAny]

#     async def post(self, request):
#         id_token_str = request.data.get("id_token")
#         if not id_token_str:
#             return Response(
#                 {"status": False, "message": "Missing 'id_token'"},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         try:
#             idinfo = await sync_to_async(google_id_token.verify_oauth2_token)(
#                 id_token_str,
#                 google_requests.Request(),
#                 settings.GOOGLE_CLIENT_ID,
#             )
#         except Exception as e:
#             logger.exception("GoogleMobileAuth invalid token: %s", str(e))
#             return Response(
#                 {"status": False, "message": "Invalid Google token"},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         email = (idinfo.get("email") or "").strip().lower()
#         if not email:
#             return Response(
#                 {"status": False, "message": "Google token missing email"},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         if idinfo.get("email_verified") is False:
#             return Response(
#                 {"status": False, "message": "Google email is not verified"},
#                 status=status.HTTP_400_BAD_REQUEST,
#             )

#         first_name = idinfo.get("given_name", "") or ""
#         last_name = idinfo.get("family_name", "") or ""
#         username = email.split("@")[0]

#         user, created = await sync_to_async(User.objects.get_or_create, thread_sensitive=True)(
#             email=email,
#             defaults={
#                 "username": username,
#                 "first_name": first_name,
#                 "last_name": last_name,
#             },
#         )

#         if created:
#             user.set_password(get_random_string(20))
#             await sync_to_async(user.save, thread_sensitive=True)()

#         await sync_to_async(UserProfile.objects.get_or_create, thread_sensitive=True)(appuser=user, defaults={"age": 0})

#         refresh = RefreshToken.for_user(user)

#         logger.info("GoogleMobileAuth success: user_id=%s email=%s", user.id, user.email)
#         return Response(
#             {
#                 "status": True,
#                 "message": "Google login successful",
#                 "data": {
#                     "token": {
#                         "refresh": str(refresh),
#                         "access": str(refresh.access_token),
#                     },
#                     "user": {
#                         "id": user.id,
#                         "username": user.username,
#                         "email": user.email,
#                         "name": user.get_full_name(),
#                         "first_name": user.first_name,
#                         "last_name": user.last_name,
#                     },
#                 },
#             },
#             status=status.HTTP_200_OK,
#         )
