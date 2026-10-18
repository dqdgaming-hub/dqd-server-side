"""User-facing exclusive event serializers."""

from rest_framework import serializers

from gaming.models import EventBooking, ExclusiveEvent
from gaming.serializers.common import EncryptedImageField
from gaming.utils.image_encryption import safe_image_to_data_uri


class UpcomingEventSerializer(serializers.ModelSerializer):
    available_slots = serializers.ReadOnlyField()
    image = EncryptedImageField(read_only=True)

    class Meta:
        model = ExclusiveEvent
        fields = [
            "id",
            "title",
            "description",
            "event_date",
            "start_time",
            "end_time",
            "price",
            "max_participants",
            "available_slots",
            "image",
        ]


class EventBookingSerializer(serializers.ModelSerializer):

    event_title = serializers.CharField(source="event.title", read_only=True)
    event_description = serializers.CharField(source="event.description", read_only=True)
    event_date = serializers.DateField(source="event.event_date", read_only=True)
    start_time = serializers.TimeField(source="event.start_time", read_only=True)
    end_time = serializers.TimeField(source="event.end_time", read_only=True)

    event_image = serializers.SerializerMethodField()
    qr_code = serializers.SerializerMethodField()

    class Meta:
        model = EventBooking
        fields = [
            "id",

            "booking_id",

            "event",

            "event_title",
            "event_description",
            "event_image",

            "event_date",
            "start_time",
            "end_time",

            "full_name",
            "email",
            "phone",

            "amount_paid",

            "status",

            "approved_at",

            "checked_in",
            "checked_in_at",

            "qr_token",
            "qr_code",

            "created_at",
        ]

    def get_event_image(self, obj):
        return safe_image_to_data_uri(obj.event.image)

    def get_qr_code(self, obj):
        return safe_image_to_data_uri(obj.qr_code)
