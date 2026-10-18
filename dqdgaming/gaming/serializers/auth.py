"""Registration, login, social login and password reset serializers."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers, status as http_status
from rest_framework.exceptions import APIException
from rest_framework_simplejwt.tokens import RefreshToken

from gaming.auth_security import (
    LoginLocked,
    check_not_locked,
    register_failure,
    reset_failures,
)
from gaming.models import CustomUser, TermsAndConditions
from gaming.serializers.common import (
    clean_phone_field,
    ensure_email_available,
    ensure_phone_available,
)
from gaming.utils.phone import phone_lookup_values


class LoginLockedError(APIException):
    status_code = http_status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "account_locked"

    def __init__(self, detail, retry_after_seconds):
        super().__init__({"detail": detail, "locked": True, "retry_after": int(retry_after_seconds)})
        self.wait = int(retry_after_seconds)


class InvalidCredentialsError(APIException):
    # 400 (not 401) so the frontend's token-refresh interceptor stays out of it.
    status_code = http_status.HTTP_400_BAD_REQUEST
    default_code = "invalid_credentials"

    def __init__(self, detail, attempts_left):
        super().__init__({"detail": detail, "attempts_left": attempts_left})


def validate_login_allowed(user):
    if not user:
        raise serializers.ValidationError("Invalid email or password.")
    if not user.is_active:
        raise serializers.ValidationError("This account has been deactivated.")
    if user.is_deleted:
        raise serializers.ValidationError("This account is no longer available.")


def touch_last_login(user):
    user.last_login = timezone.now()
    user.save(update_fields=["last_login", "updated_at"])


def get_tokens_for_user(user):
    """Return a dict with access + refresh JWT strings."""
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


class RegisterSerializer(serializers.Serializer):
    """Minimal sign-up: name, mobile number, password (+ optional email)."""

    first_name = serializers.CharField(max_length=100, trim_whitespace=True)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    password = serializers.CharField(write_only=True, min_length=8, max_length=128)
    password2 = serializers.CharField(write_only=True, required=False, allow_blank=True)
    accept_terms = serializers.BooleanField(write_only=True)
    terms_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)

    def validate_first_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name is required.")
        return value

    def validate_phone(self, value):
        phone = clean_phone_field(value, required=True)
        ensure_phone_available(phone)
        return phone

    def validate_email(self, value):
        email = (value or "").strip().lower() or None
        ensure_email_available(email)
        return email

    def validate(self, attrs):
        if attrs.get("password2") and attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError({"password2": "Passwords do not match."})

        try:
            validate_password(
                attrs["password"],
                user=CustomUser(
                    first_name=attrs["first_name"],
                    email=attrs.get("email"),
                    phone=attrs["phone"],
                ),
            )
        except DjangoValidationError as e:
            raise serializers.ValidationError({"password": list(e.messages)})

        if not attrs["accept_terms"]:
            raise serializers.ValidationError(
                {"accept_terms": "You must accept the Terms & Conditions."}
            )

        terms = TermsAndConditions.objects.filter(
            is_current=True, is_active=True, is_deleted=False
        )
        if attrs.get("terms_id"):
            terms = terms.filter(id=attrs["terms_id"])
        attrs["terms"] = terms.first()
        if attrs.get("terms_id") and attrs["terms"] is None:
            raise serializers.ValidationError(
                {"terms_id": "The Terms & Conditions have changed. Please reload and accept them again."}
            )

        return attrs

    def create(self, validated_data):
        terms = validated_data.get("terms")
        return CustomUser.objects.create_user(
            email=validated_data.get("email"),
            password=validated_data["password"],
            first_name=validated_data["first_name"],
            last_name=validated_data.get("last_name", "").strip(),
            phone=validated_data["phone"],
            login_provider=CustomUser.LoginProvider.EMAIL,
            accepted_terms=terms,
            accepted_terms_at=timezone.now() if terms else None,
        )


def find_user_by_identifier(identifier):
    """Look a user up by email or mobile number."""
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    if "@" in identifier:
        return CustomUser.objects.filter(email__iexact=identifier).first()
    values = phone_lookup_values(identifier)
    if not values:
        return None
    return CustomUser.objects.filter(phone__in=values).order_by("-is_active").first()


class LoginSerializer(serializers.Serializer):
    """Email *or* mobile number + password, with lockout after N failures."""

    identifier = serializers.CharField(required=False, allow_blank=True, max_length=254)
    email = serializers.CharField(required=False, allow_blank=True, max_length=254)
    password = serializers.CharField(write_only=True, max_length=128, trim_whitespace=False)

    default_error = "Invalid mobile number / email or password."

    def validate(self, attrs):
        identifier = (attrs.get("identifier") or attrs.get("email") or "").strip()
        password = attrs.get("password") or ""
        if not identifier or not password:
            raise serializers.ValidationError("Enter your mobile number or email and password.")

        user = find_user_by_identifier(identifier)

        try:
            check_not_locked(user, identifier)
        except LoginLocked as exc:
            raise LoginLockedError(str(exc), exc.retry_after_seconds)

        password_ok = False
        if user is not None:
            password_ok = user.check_password(password)
        else:
            # Spend the same time hashing so response timing doesn't reveal
            # whether the account exists.
            CustomUser().set_password(password)

        if not password_ok:
            try:
                attempts_left = register_failure(user, identifier)
            except LoginLocked as exc:
                raise LoginLockedError(str(exc), exc.retry_after_seconds)
            raise InvalidCredentialsError(
                f"{self.default_error} {attempts_left} attempt"
                f"{'s' if attempts_left != 1 else ''} left.",
                attempts_left,
            )

        if not user.is_active or user.is_deleted:
            raise serializers.ValidationError("This account has been deactivated. Please contact us.")

        reset_failures(user)
        attrs["user"] = user
        return attrs


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate_new_password(self, value):
        try:
            validate_password(value, self.context["request"].user)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def save(self):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save()
        return user


class GoogleLoginSerializer(serializers.Serializer):
    """
    Receives the id_token from Google Sign-In / One Tap.
    The view verifies the token and upserts the user.
    """

    id_token = serializers.CharField()


class GoogleCodeLoginSerializer(serializers.Serializer):
    code = serializers.CharField()
    redirect_uri = serializers.URLField()


class FacebookLoginSerializer(serializers.Serializer):
    """
    Receives the short-lived access_token from FB.login().
    The view exchanges it with the Graph API and upserts the user.
    """

    access_token = serializers.CharField()


class ChangePasswordSerializer(serializers.Serializer):

    current_password = serializers.CharField(write_only=True)

    new_password = serializers.CharField(write_only=True)

    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):

        user = self.context["request"].user

        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError(
                {"current_password": "Current password is incorrect."}
            )

        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )

        if attrs["current_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": "New password must be different."}
            )

        validate_password(
            attrs["new_password"],
            user,
        )

        return attrs


class ForgotPasswordSerializer(serializers.Serializer):

    email = serializers.EmailField()

    def validate_email(self, value):
        return value.strip().lower()


class VerifyForgotOTPSerializer(serializers.Serializer):

    email = serializers.EmailField()

    otp = serializers.RegexField(
        regex=r"^\d{6}$",
        max_length=6,
        min_length=6,
    )


class ResetPasswordSerializer(serializers.Serializer):

    email = serializers.EmailField()

    otp = serializers.RegexField(
        regex=r"^\d{6}$",
        max_length=6,
        min_length=6,
    )

    new_password = serializers.CharField()

    confirm_password = serializers.CharField()

    def validate(self, attrs):

        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )

        validate_password(attrs["new_password"])

        return attrs
