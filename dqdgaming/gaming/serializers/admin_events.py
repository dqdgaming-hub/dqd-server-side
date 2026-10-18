"""Admin event-booking serializers."""

from rest_framework import serializers

from gaming.models import EventBooking
from gaming.serializers.common import EncryptedImageField
from gaming.utils.image_encryption import safe_image_to_data_uri


class AdminEventBookingSerializer(serializers.ModelSerializer):

    event_title = serializers.CharField(source="event.title", read_only=True)

    class Meta:
        model = EventBooking
        fields = [
            "id",
            "booking_id",
            "event",
            "event_title",
            "user",
            "full_name",
            "email",
            "phone",
            "amount_paid",
            "status",
            "qr_sent",
            "checked_in",
            "created_at",
        ]


class AdminEventBookingDetailSerializer(serializers.ModelSerializer):

    event_title = serializers.CharField(source="event.title", read_only=True)

    qr_code_url = serializers.SerializerMethodField()
    qr_code = EncryptedImageField(read_only=True)
    members = serializers.SerializerMethodField()

    class Meta:
        model = EventBooking
        fields = "__all__"

    def get_members(self, obj):
        return [{"id": str(m.id), "name": m.name, "phone": m.phone} for m in obj.members.all()]

    def get_qr_code_url(self, obj):

        if not obj.qr_code:
            return None

        request = self.context.get("request")

        if request:
            return safe_image_to_data_uri(obj.qr_code)

        return safe_image_to_data_uri(obj.qr_code)


class AdminEventBookingCreateSerializer(serializers.ModelSerializer):

    qr_code = EncryptedImageField(read_only=True)

    class Meta:
        model = EventBooking
        fields = "__all__"

    def create(self, validated_data):

        user = validated_data.get("user")

        if user:

            validated_data["full_name"] = (
                validated_data.get("full_name") or user.full_name
            )

            validated_data["email"] = validated_data.get("email") or user.email

            validated_data["phone"] = validated_data.get("phone") or user.phone

        return super().create(validated_data)
