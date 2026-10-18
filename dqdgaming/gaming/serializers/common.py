"""Shared serializer fields and validation helpers."""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from gaming.models import CustomUser
from gaming.utils.image_encryption import encrypt_uploaded_image, safe_image_to_data_uri
from gaming.utils.phone import InvalidPhone, normalize_phone, phone_lookup_values


class EncryptedImageField(serializers.Field):
    """
    Encrypt uploaded images before they are stored in a BinaryField.
    Decrypt stored images and return a frontend-ready data URI.
    """

    default_error_messages = {
        "invalid": "A valid image file is required.",
    }

    def to_internal_value(self, data):
        if data is None:
            if self.allow_null:
                return None
            self.fail("invalid")

        try:
            payload = encrypt_uploaded_image(data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        except (TypeError, ValueError, OSError) as exc:
            raise serializers.ValidationError(str(exc))

        return payload.encrypted_content

    def to_representation(self, value):
        return safe_image_to_data_uri(value)


def clean_phone_field(value, *, required=False):
    try:
        return normalize_phone(value, required=required)
    except InvalidPhone as exc:
        raise serializers.ValidationError(str(exc))


def ensure_phone_available(phone, exclude_pk=None):
    if not phone:
        return
    queryset = CustomUser.objects.filter(phone__in=phone_lookup_values(phone) | {phone})
    if exclude_pk:
        queryset = queryset.exclude(pk=exclude_pk)
    if queryset.exists():
        raise serializers.ValidationError("An account with this mobile number already exists.")


def ensure_email_available(email, exclude_pk=None):
    if not email:
        return
    queryset = CustomUser.objects.filter(email__iexact=email)
    if exclude_pk:
        queryset = queryset.exclude(pk=exclude_pk)
    if queryset.exists():
        raise serializers.ValidationError("An account with this email already exists.")


def absolute_media_url(request, file_field):
    """
    Keep the existing helper name for compatibility.
    BinaryField images are returned as decrypted data URIs.
    """
    return safe_image_to_data_uri(file_field)


def combo_price(obj):
    return getattr(obj, "combo_price", getattr(obj, "price", None))


def combo_max_people(obj):
    if getattr(obj, "max_people", None):
        return obj.max_people
    for field_name in (
        "max_people",
        "max_players",
        "people_count",
        "player_count",
        "capacity",
    ):
        value = getattr(obj, field_name, None)
        if value is not None:
            return value
    return 1
