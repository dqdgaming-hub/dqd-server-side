"""Admin user-management serializers."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers

from gaming.models import CustomUser, LoginActivity, UserDevice
from gaming.serializers.common import (
    clean_phone_field,
    ensure_email_available,
    ensure_phone_available,
)
from gaming.utils.image_encryption import safe_image_to_data_uri


class AdminUserListSerializer(serializers.ModelSerializer):

    full_name = serializers.ReadOnlyField()
    profile_image = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "first_name",
            "last_name",
            "full_name",
            "profile_image",
            "email",
            "phone",
            "role",
            "is_active",
            "is_verified",
            "is_locked",
            "loyalty_points",
            "created_at",
        ]

    is_locked = serializers.SerializerMethodField()

    def get_is_locked(self, obj):
        return bool(obj.locked_until and obj.locked_until > timezone.now())

    def get_profile_image(self, obj):
        return safe_image_to_data_uri(obj.profile_image)


class AdminUserWriteSerializer(serializers.Serializer):
    """Admin creates / edits a customer: name, mobile and a password."""

    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    password = serializers.CharField(
        max_length=128, required=False, allow_blank=True, trim_whitespace=False, write_only=True
    )
    is_active = serializers.BooleanField(required=False)

    def validate_first_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name is required.")
        return value

    def validate_phone(self, value):
        phone = clean_phone_field(value, required=True)
        ensure_phone_available(phone, exclude_pk=getattr(self.instance, "pk", None))
        return phone

    def validate_email(self, value):
        email = (value or "").strip().lower() or None
        ensure_email_available(email, exclude_pk=getattr(self.instance, "pk", None))
        return email

    def validate(self, attrs):
        password = attrs.get("password") or ""
        if self.instance is None and not password:
            raise serializers.ValidationError({"password": "Password is required."})
        if password:
            candidate = self.instance or CustomUser()
            candidate.first_name = attrs.get("first_name", candidate.first_name)
            candidate.phone = attrs.get("phone", candidate.phone)
            try:
                validate_password(password, user=candidate)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    def create(self, validated_data):
        validated_data.pop("is_active", None)
        password = validated_data.pop("password")
        return CustomUser.objects.create_user(
            password=password,
            role=CustomUser.Role.USER,
            login_provider=CustomUser.LoginProvider.EMAIL,
            **validated_data,
        )

    def update(self, instance, validated_data):
        password = validated_data.pop("password", "") or ""
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
            instance.failed_login_attempts = 0
            instance.locked_until = None
        instance.save()
        return instance


class AdminUserDeviceSerializer(serializers.ModelSerializer):
    is_online = serializers.BooleanField(source="is_currently_online", read_only=True)

    class Meta:
        model = UserDevice
        fields = [
            "id",
            "device_id",
            "device_name",
            "device_type",
            "browser",
            "operating_system",
            "ip_address",
            "screen_resolution",
            "time_zone",
            "language",
            "first_ip_address",
            "is_online",
            "login_at",
            "last_seen",
            "logged_out_at",
        ]


class AdminLoginActivitySerializer(serializers.ModelSerializer):
    event_label = serializers.CharField(source="get_event_display", read_only=True)

    class Meta:
        model = LoginActivity
        fields = [
            "id",
            "event",
            "event_label",
            "identifier",
            "ip_address",
            "device_id",
            "device_name",
            "device_type",
            "browser",
            "operating_system",
            "detail",
            "created_at",
        ]


class AdminUserDetailSerializer(serializers.ModelSerializer):

    full_name = serializers.ReadOnlyField()

    devices = serializers.SerializerMethodField()
    recent_logins = serializers.SerializerMethodField()

    total_bookings = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "full_name",
            "email",
            "phone",
            "gender",
            "profile_image",
            "role",
            "is_active",
            "is_verified",
            "loyalty_points",
            "created_at",
            "devices",
            "recent_logins",
            "total_bookings",
        ]

    def get_devices(self, obj):
        devices = obj.devices.filter(is_deleted=False).order_by("-last_seen")
        return AdminUserDeviceSerializer(devices, many=True).data

    def get_recent_logins(self, obj):
        activity = obj.login_activities.all()[:20]
        return AdminLoginActivitySerializer(activity, many=True).data

    def get_total_bookings(self, obj):
        return obj.bookings.count()

    def get_profile_image(self, obj):
        return safe_image_to_data_uri(obj.profile_image)
