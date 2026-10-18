"""User profile, navbar and device serializers."""

from rest_framework import serializers

from gaming.models import CustomUser, UserDevice
from gaming.serializers.common import (
    EncryptedImageField,
    clean_phone_field,
    ensure_email_available,
    ensure_phone_available,
)
from gaming.tracking import parse_device_id
from gaming.utils.image_encryption import safe_image_to_data_uri


class UserProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    profile_image = EncryptedImageField(required=False, allow_null=True)

    class Meta:
        model = CustomUser
        fields = (
            "id",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone",
            "dob",
            "gender",
            "profile_image",
            "role",
            "login_provider",
            "loyalty_points",
            "is_verified",
            "created_at",
        )
        read_only_fields = (
            "id",
            "email",
            "role",
            "login_provider",
            "loyalty_points",
            "is_verified",
            "created_at",
        )

    def validate_phone(self, value):
        phone = clean_phone_field(value)
        ensure_phone_available(phone, exclude_pk=getattr(self.instance, "pk", None))
        return phone

    def validate_email(self, value):
        email = (value or "").strip().lower() or None
        ensure_email_available(email, exclude_pk=getattr(self.instance, "pk", None))
        return email

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class UserDetailsSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    profile_image = EncryptedImageField(read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "full_name",
            "email",
            "phone",
            "profile_image",
            "loyalty_points",
        ]


class NavbarUserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    profile_image = EncryptedImageField(read_only=True)
    profile_image_url = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = (
            "id",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "role",
            "profile_image",
            "profile_image_url",
            "loyalty_points",  # ← add this
            "is_verified",
        )
        read_only_fields = fields

    def get_profile_image_url(self, obj):
        if not obj.profile_image:
            return None

        return safe_image_to_data_uri(obj.profile_image)


class UserDeviceSerializer(serializers.ModelSerializer):
    is_current_device = serializers.SerializerMethodField()
    is_online = serializers.BooleanField(source="is_currently_online", read_only=True)

    class Meta:
        model = UserDevice
        fields = (
            "id",
            "device_id",
            "ip_address",
            "browser",
            "operating_system",
            "device_name",
            "device_type",
            "screen_resolution",
            "time_zone",
            "language",
            "last_seen",
            "login_at",
            "logged_out_at",
            "is_online",
            "is_current_device",
        )
        read_only_fields = fields

    def get_is_current_device(self, obj):
        request = self.context.get("request")
        return bool(request and parse_device_id(request) == obj.device_id)


class ProfileSerializer(serializers.ModelSerializer):
    profile_image = EncryptedImageField(required=False, allow_null=True)

    class Meta:
        model = CustomUser

        fields = [
            "id",
            "profile_image",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone",
            "dob",
            "gender",
            "role",
            "login_provider",
            "loyalty_points",
            "is_verified",
            "created_at",
            "last_login",
        ]

        read_only_fields = [
            "id",
            "role",
            "login_provider",
            "loyalty_points",
            "is_verified",
            "created_at",
            "last_login",
        ]

        extra_kwargs = {
            "first_name": {
                "required": False,
                "allow_blank": True,
            },
            "last_name": {
                "required": False,
                "allow_blank": True,
            },
            "email": {
                "required": False,
                "allow_blank": True,
            },
            "phone": {
                "required": False,
                "allow_blank": True,
            },
            "gender": {
                "required": False,
                "allow_blank": True,
            },
            "dob": {
                "required": False,
                "allow_null": True,
            },
        }

    def validate_phone(self, value):
        phone = clean_phone_field(value)
        ensure_phone_available(phone, exclude_pk=getattr(self.instance, "pk", None))
        return phone

    def validate_email(self, value):
        email = (value or "").strip().lower() or None
        ensure_email_available(email, exclude_pk=getattr(self.instance, "pk", None))
        return email

    def validate(self, attrs):
        email = attrs.get("email", getattr(self.instance, "email", None))
        phone = attrs.get("phone", getattr(self.instance, "phone", None))
        if not email and not phone:
            raise serializers.ValidationError("Keep at least a mobile number or an email on your account.")
        return attrs
