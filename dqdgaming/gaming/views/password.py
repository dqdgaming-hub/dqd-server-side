"""Password change and password reset (link and OTP) views."""

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, identify_hasher, make_password
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import permissions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView

from gaming.auth_security import OTPLimitReached, check_otp_send_allowed, reset_failures
from gaming.middleware import DeviceActivityMixin
from gaming.models import CustomUser, LoginActivity, PasswordResetOTP, UserDevice
from gaming.serializers import (
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    PasswordChangeSerializer,
    ResetPasswordSerializer,
    VerifyForgotOTPSerializer,
)
from gaming.tracking import record_login_activity

logger = logging.getLogger(__name__)


class PasswordChangeView(DeviceActivityMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {"detail": "Password updated successfully."},
            status=status.HTTP_200_OK,
        )


class PasswordResetRequestView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        email = request.data.get("email", "").strip().lower()

        if email:
            user = CustomUser.objects.filter(
                email__iexact=email,
                is_active=True,
                is_deleted=False,
            ).first()

            if user:
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                frontend_url = settings.FRONTEND_URL.rstrip("/")
                link = f"{frontend_url}/reset-password/" f"{uid}/{token}/"

                try:
                    send_mail(
                        subject="Reset your DQD Gaming password",
                        message=(
                            "Reset your password using the following " f"link:\n{link}"
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                except Exception:
                    logger.exception(
                        "Password reset email failed for %s.",
                        user.email,
                    )

        return Response(
            {
                "detail": (
                    "If that email is registered, you will receive "
                    "a reset link shortly."
                )
            },
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        uid = request.data.get("uid", "")
        token = request.data.get("token", "")
        new_password = request.data.get("new_password", "")

        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = CustomUser.objects.get(
                pk=user_id,
                is_active=True,
                is_deleted=False,
            )
        except (
            CustomUser.DoesNotExist,
            ValueError,
            TypeError,
            OverflowError,
        ):
            return Response(
                {"detail": "Invalid reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not default_token_generator.check_token(user, token):
            return Response(
                {"detail": "Reset link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return Response(
                {"new_password": list(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])

        UserDevice.objects.filter(
            user=user,
            is_online=True,
        ).update(
            is_online=False,
            logged_out_at=timezone.now(),
        )

        return Response(
            {"detail": "Password has been reset successfully."},
            status=status.HTTP_200_OK,
        )


class ChangePasswordAPIView(APIView):

    permission_classes = [
        IsAuthenticated,
    ]

    def post(self, request):

        serializer = ChangePasswordSerializer(
            data=request.data,
            context={
                "request": request,
            },
        )

        serializer.is_valid(raise_exception=True)

        user = request.user

        user.set_password(serializer.validated_data["new_password"])

        user.save()

        return Response(
            {
                "success": True,
                "message": "Password changed successfully.",
            }
        )


class ForgotPasswordAPIView(APIView):

    permission_classes = []
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "password_reset"

    @transaction.atomic
    def post(self, request):

        serializer = ForgotPasswordSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        user = CustomUser.objects.select_for_update().filter(
            email__iexact=email,
            is_active=True,
            is_deleted=False,
        ).first()

        try:
            resends_left = check_otp_send_allowed(user, email)
        except OTPLimitReached as exc:
            return Response(
                {
                    "success": False,
                    "detail": str(exc),
                    "message": str(exc),
                    "resends_left": 0,
                    "retry_after": exc.retry_after_seconds,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        generic_message = (
            "If an account with that email exists, a reset code has been sent."
        )

        if user is None:
            return Response(
                {
                    "success": True,
                    "message": generic_message,
                    "resends_left": resends_left,
                },
                status=status.HTTP_200_OK,
            )

        # Keep old codes (marked used) so they count toward the resend limit.
        PasswordResetOTP.objects.filter(
            user=user,
            is_used=False,
        ).update(is_used=True)

        otp = PasswordResetOTP.generate_otp()

        otp_record = PasswordResetOTP.objects.create(
            user=user,
            otp=make_password(otp),
            expires_at=timezone.now() + timedelta(minutes=10),
        )

        try:
            sent_count = send_mail(
                subject="Your DQD Gaming password reset code",
                message=(
                    f"Your password reset code is {otp}.\n\n"
                    "This code expires in 10 minutes. If you did not request "
                    "a password reset, you can ignore this email."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
            if not sent_count:
                raise RuntimeError("The email backend did not send the reset code.")
        except Exception:
            otp_record.delete()
            logger.exception("Password-reset email failed for %s.", user.email)
            return Response(
                {
                    "success": False,
                    "detail": "Unable to send a reset code right now. Please try again shortly.",
                    "message": "Unable to send a reset code right now. Please try again shortly.",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "success": True,
                "message": generic_message,
                "resends_left": resends_left,
            }
        )


PASSWORD_RESET_OTP_MAX_ATTEMPTS = 5


def _validate_password_reset_otp(user, submitted_otp):
    otp_record = (
        PasswordResetOTP.objects.select_for_update()
        .filter(user=user, is_used=False)
        .order_by("-created_at")
        .first()
    )

    if otp_record is None:
        return None

    if otp_record.is_expired():
        otp_record.is_used = True
        otp_record.save(update_fields=["is_used", "updated_at"])
        return None

    if otp_record.attempts >= PASSWORD_RESET_OTP_MAX_ATTEMPTS:
        otp_record.is_used = True
        otp_record.save(update_fields=["is_used", "updated_at"])
        return None

    otp_record.attempts += 1

    try:
        identify_hasher(otp_record.otp)
    except ValueError:
        is_valid = secrets.compare_digest(otp_record.otp, submitted_otp)
        if is_valid:
            otp_record.otp = make_password(submitted_otp)
    else:
        is_valid = check_password(submitted_otp, otp_record.otp)

    if not is_valid and otp_record.attempts >= PASSWORD_RESET_OTP_MAX_ATTEMPTS:
        otp_record.is_used = True

    otp_record.save(
        update_fields=["otp", "attempts", "is_used", "updated_at"]
    )
    return otp_record if is_valid else None


class VerifyForgotOTPAPIView(APIView):

    permission_classes = []
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "password_reset"

    @transaction.atomic
    def post(self, request):

        serializer = VerifyForgotOTPSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        user = CustomUser.objects.filter(
            email__iexact=serializer.validated_data["email"],
            is_active=True,
            is_deleted=False,
        ).first()
        if user is None or not _validate_password_reset_otp(
            user,
            serializer.validated_data["otp"],
        ):
            return Response(
                {"success": False, "message": "Invalid or expired reset code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"success": True, "message": "OTP verified successfully."})


class ResetPasswordAPIView(APIView):

    permission_classes = []
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = "password_reset"

    @transaction.atomic
    def post(self, request):

        serializer = ResetPasswordSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        user = CustomUser.objects.select_for_update().filter(
            email__iexact=serializer.validated_data["email"],
            is_active=True,
            is_deleted=False,
        ).first()
        if user is None:
            return Response(
                {"success": False, "message": "Invalid or expired reset code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp_record = _validate_password_reset_otp(
            user,
            serializer.validated_data["otp"],
        )
        if otp_record is None:
            return Response(
                {"success": False, "message": "Invalid or expired reset code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(serializer.validated_data["new_password"])

        user.save(update_fields=["password", "updated_at"])
        reset_failures(user)
        record_login_activity(
            request, LoginActivity.Event.PASSWORD_RESET, user=user, identifier=user.email or ""
        )

        PasswordResetOTP.objects.filter(
            user=user,
            is_used=False,
        ).update(is_used=True)

        return Response({"success": True, "message": "Password reset successfully."})
