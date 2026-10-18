"""Registration, login/logout, email verification and social login views."""

import logging
import os
from smtplib import SMTPException
from urllib.parse import urlparse

import requests as http_requests
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from gaming.middleware import DeviceActivityMixin
from gaming.models import CustomUser, LoginActivity
from gaming.serializers import (
    FacebookLoginSerializer,
    GoogleCodeLoginSerializer,
    GoogleLoginSerializer,
    LoginLockedError,
    LoginSerializer,
    RegisterSerializer,
    UserProfileSerializer,
    find_user_by_identifier,
    get_tokens_for_user,
    touch_last_login,
    validate_login_allowed,
)
from gaming.tracking import (
    mark_current_device_offline,
    record_login_activity,
    register_device,
)
from gaming.utils.image_encryption import encrypt_image_bytes

logger = logging.getLogger(__name__)


def _build_token_response(
    user,
    request=None,
    is_new=False,
    include_is_new=False,
):
    data = {
        **get_tokens_for_user(user),
        "user": UserProfileSerializer(
            user,
            context={"request": request},
        ).data,
    }

    if include_is_new:
        data["is_new"] = is_new

    return data


def _role_redirect_path(user):
    if user.role == CustomUser.Role.ADMIN:
        return "/admin/dashboard"

    return "/user/dashboard"


def _persist_remote_profile_image(user, image_url):
    if not image_url or user.profile_image:
        return []

    try:
        response = http_requests.get(
            image_url,
            timeout=10,
            stream=True,
        )
        response.raise_for_status()
    except http_requests.RequestException as exc:
        logger.warning(
            "Could not fetch profile image for %s: %s",
            user.email,
            exc,
        )
        return []

    content_type = response.headers.get("Content-Type", "").lower()

    if not content_type.startswith("image/"):
        return []

    content = response.content

    if len(content) > 2 * 1024 * 1024:
        logger.warning(
            "Profile image for %s exceeded the 2MB limit.",
            user.email,
        )
        return []

    try:
        payload = encrypt_image_bytes(
            content=content,
            filename=os.path.basename(image_url.split("?", 1)[0]),
        )
    except DjangoValidationError as exc:
        logger.warning(
            "Profile image for %s could not be encrypted: %s",
            user.email,
            exc,
        )
        return []

    user.profile_image = payload.encrypted_content
    return ["profile_image"]


def _finalize_login_response(
    user,
    request,
    is_new=False,
    include_is_new=False,
):
    validate_login_allowed(user)
    touch_last_login(user)

    response_data = _build_token_response(
        user,
        request=request,
        is_new=is_new,
        include_is_new=include_is_new,
    )
    response_data["redirect_to"] = _role_redirect_path(user)

    return response_data


def _finalize_device_login(
    user,
    request,
    *,
    is_new=False,
    include_is_new=False,
    event=LoginActivity.Event.LOGIN_SUCCESS,
    identifier="",
):
    response_data = _finalize_login_response(
        user,
        request,
        is_new=is_new,
        include_is_new=include_is_new,
    )

    device = register_device(request, user)
    response_data["device_id"] = str(device.device_id)

    record_login_activity(
        request,
        event,
        user=user,
        identifier=identifier or user.email or user.phone or "",
        device_id=device.device_id,
        detail="new account" if is_new else "",
    )

    return response_data


def _send_verification_email(user):
    if not user.email:
        return
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    frontend_url = settings.FRONTEND_URL.rstrip("/")
    link = f"{frontend_url}/verify-email/{uid}/{token}/"

    send_mail(
        subject="Verify your DQD Gaming account",
        message=(
            f"Hi {user.first_name},\n\n"
            f"Verify your email using the following link:\n{link}"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def _log_verification_email_failure(operation, error):
    logger.warning(
        "Verification email %s failed (%s).",
        operation,
        type(error).__name__,
    )


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "register"

    def post(self, request):
        serializer = RegisterSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        try:
            _send_verification_email(user)
        except (SMTPException, OSError) as error:
            _log_verification_email_failure("during registration", error)

        return Response(
            _finalize_device_login(user, request, event=LoginActivity.Event.REGISTER),
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = LoginSerializer(
            data=request.data,
            context={"request": request},
        )
        identifier = str(
            request.data.get("identifier") or request.data.get("email") or ""
        ).strip()[:254]
        try:
            serializer.is_valid(raise_exception=True)
        except LoginLockedError as exc:
            record_login_activity(
                request,
                LoginActivity.Event.LOGIN_LOCKED,
                user=find_user_by_identifier(identifier),
                identifier=identifier,
                detail=str(exc.detail.get("detail", ""))[:255],
            )
            raise
        except Exception as exc:
            record_login_activity(
                request,
                LoginActivity.Event.LOGIN_FAILED,
                user=find_user_by_identifier(identifier),
                identifier=identifier,
                detail=type(exc).__name__,
            )
            raise

        user = serializer.validated_data["user"]
        response_data = _finalize_device_login(user, request, identifier=identifier)

        if user.email and not user.is_verified:
            response_data["email_unverified"] = True

        return Response(
            response_data,
            status=status.HTTP_200_OK,
        )


class LogoutView(DeviceActivityMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            refresh = RefreshToken(refresh_token)
            token_user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)
            if str(token_user_id) != str(request.user.pk):
                raise TokenError("Refresh token does not belong to this user.")

            refresh.blacklist()
        except TokenError:
            return Response(
                {"detail": "Invalid or expired refresh token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        mark_current_device_offline(request)
        record_login_activity(request, LoginActivity.Event.LOGOUT, user=request.user)
        return Response(
            {"detail": "Successfully logged out."},
            status=status.HTTP_200_OK,
        )


class EmailVerifyView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        uid = request.data.get("uid", "")
        token = request.data.get("token", "")

        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = CustomUser.objects.get(
                pk=user_id,
                is_deleted=False,
            )
        except (
            CustomUser.DoesNotExist,
            ValueError,
            TypeError,
            OverflowError,
        ):
            return Response(
                {"detail": "Invalid verification link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not default_token_generator.check_token(user, token):
            return Response(
                {"detail": ("Verification link is invalid or has expired.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not user.is_verified:
            user.is_verified = True
            user.save(update_fields=["is_verified", "updated_at"])

        return Response(
            {"detail": "Email verified successfully."},
            status=status.HTTP_200_OK,
        )


class EmailResendView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get("email", "").strip().lower()

        user = CustomUser.objects.filter(
            email__iexact=email,
            is_active=True,
            is_deleted=False,
            is_verified=False,
        ).first()

        if user:
            try:
                _send_verification_email(user)
            except (SMTPException, OSError) as error:
                _log_verification_email_failure("during resend", error)

        return Response(
            {
                "detail": (
                    "If that email is pending verification, "
                    "a new link has been sent."
                )
            },
            status=status.HTTP_200_OK,
        )


class GoogleLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "social_login"

    def post(self, request):
        serializer = GoogleLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        return _complete_google_login(
            request,
            serializer.validated_data["id_token"],
        )


class GoogleCodeLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "social_login"

    def post(self, request):
        serializer = GoogleCodeLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not settings.GOOGLE_CLIENT_SECRET:
            return Response(
                {"detail": "Google redirect sign-in is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        redirect_uri = serializer.validated_data["redirect_uri"]
        parsed_redirect = urlparse(redirect_uri)
        redirect_origin = f"{parsed_redirect.scheme}://{parsed_redirect.netloc}"
        allowed_origins = {
            origin.rstrip("/") for origin in settings.CORS_ALLOWED_ORIGINS
        }

        if (
            redirect_origin not in allowed_origins
            or parsed_redirect.path != "/sign-in"
            or parsed_redirect.query
            or parsed_redirect.fragment
            or parsed_redirect.username
            or parsed_redirect.password
        ):
            return Response(
                {"detail": "Invalid Google redirect URI."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token_response = http_requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": serializer.validated_data["code"],
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=10,
            )
            token_response.raise_for_status()
            token_data = token_response.json()
        except (http_requests.RequestException, ValueError):
            logger.warning("Google authorization-code exchange failed.")
            return Response(
                {"detail": "Google sign-in could not be verified."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        id_token = token_data.get("id_token")
        if not id_token:
            return Response(
                {"detail": "Google sign-in did not return an ID token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return _complete_google_login(request, id_token)


def _complete_google_login(request, token):
    try:
        google_data = google_id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )
    except ValueError as exc:
        logger.warning(
            "Google token verification failed: %s",
            exc,
        )
        return Response(
            {"detail": "Invalid Google token."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    email = google_data.get("email", "").strip().lower()
    first_name = google_data.get("given_name", "").strip()
    last_name = google_data.get("family_name", "").strip()
    picture = google_data.get("picture", "")
    google_email_verified = google_data.get(
        "email_verified",
        False,
    )

    if not email or not google_email_verified:
        return Response(
            {"detail": "Google account email is not verified."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user, is_new = CustomUser.objects.get_or_create(
        email=email,
        defaults={
            "first_name": first_name or "Google User",
            "last_name": last_name,
            "login_provider": CustomUser.LoginProvider.GOOGLE,
            "is_verified": True,
            "role": CustomUser.Role.USER,
        },
    )

    validate_login_allowed(user)

    update_fields = []

    if not user.first_name and first_name:
        user.first_name = first_name
        update_fields.append("first_name")

    if not user.last_name and last_name:
        user.last_name = last_name
        update_fields.append("last_name")

    if not user.is_verified:
        user.is_verified = True
        update_fields.append("is_verified")

    update_fields.extend(_persist_remote_profile_image(user, picture))

    if update_fields:
        update_fields.append("updated_at")
        user.save(update_fields=list(dict.fromkeys(update_fields)))

    return Response(
        _finalize_device_login(
            user,
            request,
            is_new=is_new,
            include_is_new=True,
            event=LoginActivity.Event.SOCIAL_LOGIN,
        ),
        status=status.HTTP_200_OK,
    )


class FacebookLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "social_login"

    FB_GRAPH_URL = "https://graph.facebook.com/me"
    FB_FIELDS = "id,name,first_name,last_name,email,picture"

    def post(self, request):
        serializer = FacebookLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        access_token = serializer.validated_data["access_token"]

        try:
            response = http_requests.get(
                self.FB_GRAPH_URL,
                params={
                    "fields": self.FB_FIELDS,
                    "access_token": access_token,
                },
                timeout=10,
            )
            response.raise_for_status()
            facebook_data = response.json()
        except (
            http_requests.RequestException,
            ValueError,
        ) as exc:
            logger.warning(
                "Facebook Graph API request failed: %s",
                exc,
            )
            return Response(
                {"detail": "Could not validate Facebook token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if "error" in facebook_data:
            return Response(
                {
                    "detail": facebook_data["error"].get(
                        "message",
                        "Facebook authentication failed.",
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = facebook_data.get("email", "").strip().lower()
        first_name = facebook_data.get(
            "first_name",
            facebook_data.get("name", ""),
        ).strip()
        last_name = facebook_data.get("last_name", "").strip()

        picture = facebook_data.get("picture", {}).get("data", {}).get("url", "")

        if not email:
            return Response(
                {
                    "detail": (
                        "Facebook did not provide an email address. "
                        "Ensure the account has a verified email."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user, is_new = CustomUser.objects.get_or_create(
            email=email,
            defaults={
                "first_name": first_name or "Facebook User",
                "last_name": last_name,
                "login_provider": CustomUser.LoginProvider.FACEBOOK,
                "is_verified": True,
                "role": CustomUser.Role.USER,
            },
        )

        validate_login_allowed(user)

        update_fields = []

        if not user.first_name and first_name:
            user.first_name = first_name
            update_fields.append("first_name")

        if not user.last_name and last_name:
            user.last_name = last_name
            update_fields.append("last_name")

        if not user.is_verified:
            user.is_verified = True
            update_fields.append("is_verified")

        update_fields.extend(_persist_remote_profile_image(user, picture))

        if update_fields:
            update_fields.append("updated_at")
            user.save(update_fields=list(dict.fromkeys(update_fields)))

        return Response(
            _finalize_device_login(
                user,
                request,
                is_new=is_new,
                include_is_new=True,
                event=LoginActivity.Event.SOCIAL_LOGIN,
            ),
            status=status.HTTP_200_OK,
        )
