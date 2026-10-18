"""Loyalty points and loyalty-slot redemption serializers."""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from gaming.models import Booking, CustomUser, GamingItem, LoyaltyTransaction


class AdminUserLoyaltySerializer(serializers.ModelSerializer):

    full_name = serializers.ReadOnlyField()

    total_transactions = serializers.SerializerMethodField()

    redeemed_points = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser

        fields = [
            "id",
            "full_name",
            "email",
            "phone",
            "loyalty_points",
            "total_transactions",
            "redeemed_points",
            "is_active",
        ]

    def get_total_transactions(self, obj):
        if hasattr(obj, "total_transactions_count"):
            return obj.total_transactions_count
        return obj.loyalty_transactions.count()

    def get_redeemed_points(self, obj):
        if hasattr(obj, "redeemed_points_total"):
            return abs(obj.redeemed_points_total or 0)

        redeemed = obj.loyalty_transactions.filter(
            transaction_type=LoyaltyTransaction.TransactionType.REDEEMED
        ).aggregate(total=Sum("points"))

        return abs(redeemed["total"] or 0)


class AdminAdjustLoyaltySerializer(serializers.Serializer):
    points = serializers.IntegerField(min_value=1, max_value=100000)

    reason = serializers.CharField(max_length=500, trim_whitespace=True)

    action = serializers.ChoiceField(
        choices=[
            ("add", "Add"),
            ("deduct", "Deduct"),
        ]
    )


class LoyaltyTransactionSerializer(serializers.ModelSerializer):

    granted_by_name = serializers.CharField(
        source="granted_by.full_name",
        read_only=True,
    )

    class Meta:
        model = LoyaltyTransaction

        fields = "__all__"


class LoyaltySlotRedemptionSerializer(serializers.Serializer):
    item = serializers.PrimaryKeyRelatedField(
        queryset=GamingItem.objects.filter(is_active=True, is_deleted=False)
    )
    booking_date = serializers.DateField()
    start_time = serializers.TimeField()
    points_to_redeem = serializers.IntegerField(min_value=100)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_points_to_redeem(self, value):
        if value % 100 != 0:
            raise serializers.ValidationError(
                "Redeem points in blocks of 100. Example: 100 points = 1 hour."
            )
        return value

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user
        item = attrs["item"]
        booking_date = attrs["booking_date"]
        start_time = attrs["start_time"]
        points_to_redeem = attrs["points_to_redeem"]
        hours = points_to_redeem // 100

        if not user or not user.is_authenticated:
            raise serializers.ValidationError("Login is required to redeem points.")

        if user.loyalty_points < 100:
            raise serializers.ValidationError(
                "You need more than 100 loyalty points to redeem a slot."
            )

        if user.loyalty_points < points_to_redeem:
            raise serializers.ValidationError(
                f"You only have {user.loyalty_points} loyalty points available."
            )

        if item.maintenance_mode:
            raise serializers.ValidationError("This game item is under maintenance.")

        start_datetime = datetime.combine(booking_date, start_time)
        end_datetime = start_datetime + timedelta(hours=hours)

        if timezone.is_naive(start_datetime):
            start_datetime = timezone.make_aware(start_datetime)

        if start_datetime <= timezone.now():
            raise serializers.ValidationError("Please choose a future slot.")

        if start_datetime.date() != end_datetime.date():
            raise serializers.ValidationError("Redeemed slots must end on the same day.")

        attrs["total_hours"] = Decimal(str(hours))
        attrs["end_time"] = end_datetime.time()

        overlap_exists = Booking.objects.filter(
            item=item,
            booking_date=booking_date,
            start_time__lt=attrs["end_time"],
            end_time__gt=start_time,
        ).exclude(status=Booking.Status.CANCELLED).exists()

        if overlap_exists:
            raise serializers.ValidationError("This slot is already booked.")

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        item = validated_data["item"]
        points_to_redeem = validated_data["points_to_redeem"]

        user.__class__.objects.select_for_update().get(pk=user.pk)
        user.refresh_from_db()

        if user.loyalty_points < points_to_redeem:
            raise serializers.ValidationError(
                "Your loyalty balance changed. Please try again."
            )

        booking = Booking.objects.create(
            user=user,
            item=item,
            booking_date=validated_data["booking_date"],
            start_time=validated_data["start_time"],
            end_time=validated_data["end_time"],
            total_hours=validated_data["total_hours"], 
            subtotal=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("0.00"),
            price_paid=Decimal("0.00"),
            payment_status=Booking.PaymentStatus.PENDING,
            status=Booking.Status.PENDING,
            notes=validated_data.get("notes", ""),
        )

        user.loyalty_points -= points_to_redeem
        user.save(update_fields=["loyalty_points", "updated_at"])

        LoyaltyTransaction.objects.create(
            user=user,
            booking=booking,
            points=-points_to_redeem,
            transaction_type=LoyaltyTransaction.TransactionType.REDEEMED,
            description=(
                f"Redeemed {points_to_redeem} points for "
                f"{validated_data['total_hours']} hour slot on {item.name}."
            ),
        )

        booking.remaining_loyalty_points = user.loyalty_points
        booking.redeemed_points = points_to_redeem
        return booking


class LoyaltyRedeemedBookingSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    remaining_loyalty_points = serializers.IntegerField(read_only=True)
    redeemed_points = serializers.IntegerField(read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            "item",
            "item_name",
            "booking_date",
            "start_time",
            "end_time",
            "total_hours",
            "status",
            "payment_status",
            "redeemed_points",
            "remaining_loyalty_points",
        ]
