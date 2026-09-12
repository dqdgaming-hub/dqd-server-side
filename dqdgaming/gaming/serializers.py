# gaming/serializers.py
# ============================================================
# Serializers for:
#   - User registration  (email + optional gender/dob/phone)
#   - Login (returns JWT pair)
#   - Profile read / update
#   - Password change
#   - Google & Facebook social login
# ============================================================

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from gaming.models import CustomUser
from django.utils import timezone


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


# ── Utility ──────────────────────────────────────────────────


def get_tokens_for_user(user):
    """Return a dict with access + refresh JWT strings."""
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


# ── Registration ─────────────────────────────────────────────

class RegisterSerializer(serializers.ModelSerializer):

    password = serializers.CharField(
        write_only=True,
        min_length=8
    )

    password2 = serializers.CharField(
        write_only=True,
        label="Confirm password"
    )

    accept_terms = serializers.BooleanField(
        write_only=True,
        required=True
    )

    terms_id = serializers.UUIDField(
        write_only=True,
        required=True
    )

    class Meta:
        model = CustomUser

        fields = (
            "first_name",
            "last_name",
            "email",
            "phone",
            "gender",
            "dob",
            "password",
            "password2",
            "accept_terms",
            "terms_id",
        )

        extra_kwargs = {
            "first_name": {"required": True},
            "gender": {"required": False},
            "dob": {"required": False},
            "phone": {"required": False},
        }

    def validate_email(self, value):

        if CustomUser.objects.filter(
            email__iexact=value
        ).exists():

            raise serializers.ValidationError(
                "A user with this email already exists."
            )

        return value.lower()

    def validate(self, attrs):

        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError(
                {
                    "password2": "Passwords do not match."
                }
            )

        try:
            validate_password(attrs["password"])

        except DjangoValidationError as e:

            raise serializers.ValidationError(
                {
                    "password": list(e.messages)
                }
            )

        if not attrs["accept_terms"]:

            raise serializers.ValidationError(
                {
                    "accept_terms":
                    "You must accept the Terms & Conditions."
                }
            )

        try:

            terms = TermsAndConditions.objects.get(
                id=attrs["terms_id"],
                is_current=True,
                is_active=True,
                is_deleted=False,
            )

        except TermsAndConditions.DoesNotExist:

            raise serializers.ValidationError(
                {
                    "terms_id":
                    "Invalid Terms & Conditions."
                }
            )

        attrs["terms"] = terms

        attrs.pop("password2")
        attrs.pop("accept_terms")
        attrs.pop("terms_id")

        return attrs

    def create(self, validated_data):

        terms = validated_data.pop("terms")

        user = CustomUser.objects.create_user(

            email=validated_data["email"],

            password=validated_data["password"],

            first_name=validated_data["first_name"],

            last_name=validated_data.get("last_name", ""),

            phone=validated_data.get("phone") or None,

            gender=validated_data.get("gender", ""),

            dob=validated_data.get("dob"),

            login_provider=CustomUser.LoginProvider.EMAIL,

        )

        user.accepted_terms = terms
        user.accepted_terms_at = timezone.now()

        user.save(
            update_fields=[
                "accepted_terms",
                "accepted_terms_at",
                "updated_at",
            ]
        )

        return user
    

class RegisterResponseSerializer(serializers.Serializer):
    """Shape of the 201 response after successful registration."""

    access = serializers.CharField()
    refresh = serializers.CharField()
    user = serializers.SerializerMethodField()

    def get_user(self, obj):
        return UserProfileSerializer(obj["user"]).data


# ── Login ─────────────────────────────────────────────────────


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs["email"].lower()
        password = attrs["password"]
        user = authenticate(
            request=self.context.get("request"),
            email=email,
            password=password,
        )

        if not user:
            raise serializers.ValidationError("Invalid email or password.")

        if not user.is_active:
            raise serializers.ValidationError("This account has been deactivated.")

        # Soft-warn on unverified email instead of hard-blocking.
        # The frontend can surface a "resend verification" link when
        # the response contains  "email_unverified": true.
        # If you want a hard block, uncomment the lines below:
        #
        # if not user.is_verified:
        #     raise serializers.ValidationError(
        #         "Please verify your email before signing in."
        #     )

        attrs["user"] = user
        return attrs


# ── Profile ───────────────────────────────────────────────────


class UserProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

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

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


# ── Password change ───────────────────────────────────────────


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


# ── Google Social Login ───────────────────────────────────────


class GoogleLoginSerializer(serializers.Serializer):
    """
    Receives the id_token from Google Sign-In / One Tap.
    The view verifies the token and upserts the user.
    """

    id_token = serializers.CharField()


# ── Facebook Social Login ──────────────────────────────────────


class FacebookLoginSerializer(serializers.Serializer):
    """
    Receives the short-lived access_token from FB.login().
    The view exchanges it with the Graph API and upserts the user.
    """

    access_token = serializers.CharField()


# ── Social login shared response ─────────────────────────────


class SocialLoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    is_new = serializers.BooleanField(help_text="True if a new account was created")
    user = UserProfileSerializer()


from rest_framework import serializers
from gaming.models import *


class UserDetailsSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()

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


class GameSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = GamingItem
        fields = [
            "id",
            "name",
            "description",
            "image",
            "price_per_hour",
            "category_name",
            "maintenance_mode",
        ]


class BookingMemberSerializers(serializers.ModelSerializer):
    class Meta:
        model = BookingMember
        fields = [
            "id",
            "name",
            "phone",
            "is_admin_added",
        ]


class BookingSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    members = BookingMemberSerializers(
        many=True,
        read_only=True,
    )

    base_price = serializers.DecimalField(
        source="subtotal",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    discount_price = serializers.DecimalField(
        source="discount_amount",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    item_image = serializers.ImageField(source="item.image", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            "item_name",
            "item_image",
            "booking_date",
            "start_time",
            "end_time",
            "status",
            "payment_status",
            "base_price",
            "discount_price",
            "total_amount",
            "members",
            "created_at",
            "is_qr_valid",
        ]


class ExclusiveEventSerializer(serializers.ModelSerializer):
    available_slots = serializers.ReadOnlyField()

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
            "image",
            "available_slots",
        ]


class EventBookingSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source="event.title", read_only=True)

    event_date = serializers.DateField(source="event.event_date", read_only=True)

    event_image = serializers.ImageField(source="event.image", read_only=True)

    is_qr_valid = serializers.SerializerMethodField()

    class Meta:
        model = EventBooking
        fields = [
            "id",
            "event_title",
            "event_date",
            "event_image",
            "is_qr_valid",
        ]

    def get_is_qr_valid(self, obj):
        return obj.is_qr_valid()


class UserSpinnerRewardSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpinnerReward
        fields = [
            "id",
            "reward_name",
            "reward_type",
            "reward_points",
            "probability",
            "is_active",
        ]


class ComboPackSerializer(serializers.ModelSerializer):

    class Meta:
        model = ComboPack
        fields = [
            "id",
            "name",
            "snack_name",
            "snack_price",
            "combo_price",
            "loyalty_bonus",
            "image",
        ]


class LoyaltyTransactionSerializer(serializers.ModelSerializer):

    class Meta:
        model = LoyaltyTransaction
        fields = [
            "id",
            "points",
            "transaction_type",
            "description",
            "created_at",
        ]


class SpinnerSpinSerializer(serializers.ModelSerializer):
    reward_name = serializers.CharField(
        source="reward.reward_name",
        read_only=True,
    )
    spin_date = serializers.SerializerMethodField()

    class Meta:
        model = SpinnerSpin
        fields = [
            "id",
            "reward_name",
            "spin_date",
            "spun_at",
        ]

    def get_spin_date(self, obj):
        return obj.spun_at.date().isoformat() if obj.spun_at else None


class NavbarUserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
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

        request = self.context.get("request")
        url = obj.profile_image.url

        return request.build_absolute_uri(url) if request else url


from rest_framework import serializers
from gaming.tracking import parse_device_id
from gaming.models import UserDevice


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


from rest_framework import serializers

from gaming.models import Booking, CustomUser, GamingItem


class AdminDashboardBookingSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            "user_name",
            "user_email",
            "booking_date",
            "status",
            "total_amount",
        ]


from rest_framework import serializers


class AdminDashboardUserSerializer(serializers.ModelSerializer):

    full_name = serializers.CharField(read_only=True)
    profile_image_url = serializers.SerializerMethodField()
    is_online = serializers.BooleanField(source="is_online_flag", read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "full_name",
            "email",
            "is_active",
            "profile_image_url",
            "created_at",
            "is_online",
        ]

    def get_profile_image_url(self, user):
        if not user.profile_image:
            return None

        request = self.context.get("request")
        image_url = user.profile_image.url

        return request.build_absolute_uri(image_url) if request else image_url

    def get_is_online(self, user):
        device = (
            UserDevice.objects.filter(
                user=user,
                is_deleted=False,
            )
            .order_by("-last_seen")
            .first()
        )
        return device.is_online if device else False


class AdminDashboardDeviceSerializer(serializers.ModelSerializer):

    # is_online = serializers.BooleanField(
    #     source="is_online_flag",
    #     read_only=True
    # )
    is_online = serializers.BooleanField(source="is_currently_online", read_only=True)
    user = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = UserDevice
        fields = [
            "id",
            "device_id",
            "ip_address",
            "user",
            "browser",
            "operating_system",
            "device_name",
            "device_type",
            "login_at",
            "last_seen",
            "logged_out_at",
            "is_online",
        ]


class AdminDashboardGamingItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
    )
    reason = serializers.SerializerMethodField()

    class Meta:
        model = GamingItem
        fields = [
            "id",
            "name",
            "category_name",
            "reason",
        ]

    def get_reason(self, item):
        if item.maintenance_mode:
            return "Maintenance mode enabled."
        if not item.is_active:
            return "Gaming item is inactive."
        return "This gaming item needs attention."


from rest_framework import serializers
from gaming.models import (
    GameCategory,
    GamingItem,
    ComboPack,
    ExclusiveEvent,
)


class AdminGameCategorySerializer(serializers.ModelSerializer):

    image = serializers.SerializerMethodField()

    class Meta:
        model = GameCategory
        fields = "__all__"

    def get_image(self, obj):
        if not obj.image:
            return None

        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.image.url)

        base_url = getattr(settings, "SITE_URL", "").rstrip("/")
        return f"{base_url}{obj.image.url}"


class AdminGamingItemSerializer(serializers.ModelSerializer):

    category_name = serializers.CharField(source="category.name", read_only=True)

    image = serializers.ImageField(
            required=False,
            allow_null=True,
        )

    class Meta:
        model = GamingItem
        fields = "__all__"

    def to_representation(self, instance):
        data = super().to_representation(instance)

        if instance.image:
            request = self.context.get("request")

            if request:
                data["image"] = request.build_absolute_uri(instance.image.url)
            else:
                base_url = getattr(settings, "SITE_URL", "").rstrip("/")
                data["image"] = f"{base_url}{instance.image.url}"

        return data


class AdminComboPackSerializer(serializers.ModelSerializer):

    gaming_items = serializers.PrimaryKeyRelatedField(
        many=True, queryset=GamingItem.objects.all()
    )

    class Meta:
        model = ComboPack
        fields = "__all__"

    def to_representation(self, instance):
        data = super().to_representation(instance)

        if instance.image:
            request = self.context.get("request")
            if request:
                data["image"] = request.build_absolute_uri(instance.image.url)
            else:
                base_url = getattr(settings, "SITE_URL", "").rstrip("/")
                data["image"] = f"{base_url}{instance.image.url}"
        else:
            data["image"] = None

        return data


class AdminExclusiveEventSerializer(serializers.ModelSerializer):

    class Meta:
        model = ExclusiveEvent
        fields = "__all__"

    def create(self, validated_data):
        validated_data["is_active"] = True
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data["is_active"] = True
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)

        if instance.image:
            request = self.context.get("request")
            if request:
                data["image"] = request.build_absolute_uri(instance.image.url)
            else:
                base_url = getattr(settings, "SITE_URL", "").rstrip("/")
                data["image"] = f"{base_url}{instance.image.url}"
        else:
            data["image"] = None

        return data

class AdminUserListSerializer(serializers.ModelSerializer):

    full_name = serializers.ReadOnlyField()
    profile_image = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "full_name",
            "profile_image",
            "email",
            "phone",
            "role",
            "is_active",
            "is_verified",
            "loyalty_points",
            "created_at",
        ]

    def get_profile_image(self, obj):
        if not obj.profile_image:
            return None

        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.profile_image.url)

        base_url = getattr(settings, "SITE_URL", "").rstrip("/")
        return f"{base_url}{obj.profile_image.url}"


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
            "is_online",
            "login_at",
            "last_seen",
            "logged_out_at",
        ]


from django.conf import settings


class AdminUserDetailSerializer(serializers.ModelSerializer):

    full_name = serializers.ReadOnlyField()

    devices = AdminUserDeviceSerializer(many=True, read_only=True)

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
            "total_bookings",
        ]

    def get_total_bookings(self, obj):
        return obj.bookings.count()

    def get_profile_image(self, obj):
        if not obj.profile_image:
            return None

        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.profile_image.url)

        base_url = getattr(settings, "SITE_URL", "").rstrip("/")
        return f"{base_url}{obj.profile_image.url}"


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

    class Meta:
        model = EventBooking
        fields = "__all__"

    def get_qr_code_url(self, obj):

        if not obj.qr_code:
            return None

        request = self.context.get("request")

        if request:
            return request.build_absolute_uri(obj.qr_code.url)

        return obj.qr_code.url


class AdminEventBookingCreateSerializer(serializers.ModelSerializer):

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


"""
booking_serializers.py

Production-ready DRF serializers for the admin bookings module.

Fixes applied vs original:
  - create() was defined outside the class scope — moved inside AdminBookingCreateSerializer
  - AdminBookingDetailSerializer: explicit fields instead of __all__ to guarantee
    stable API shape and prevent accidental field exposure
  - Added validate() to AdminBookingCreateSerializer for cross-field rules
  - Added awarded_loyalty_points as a proper SerializerMethodField in detail serializer
  - Consistent null handling for combo_pack name in list serializer
  - booking_type derived from the model property, not hardcoded
"""

from rest_framework import serializers

from .models import Booking, BookingMember

# ─────────────────────────────────────────────────────────────
# Nested member serializer
# ─────────────────────────────────────────────────────────────


class BookingMemberSerializer(serializers.ModelSerializer):

    class Meta:
        model = BookingMember
        fields = [
            "id",
            "name",
            "phone",
            "is_admin_added",
        ]
        read_only_fields = ["id", "is_admin_added"]


# ─────────────────────────────────────────────────────────────
# Create serializer  (used by AdminBookingListCreateView.post)
# ─────────────────────────────────────────────────────────────


class AdminBookingCreateSerializer(serializers.ModelSerializer):

    members = BookingMemberSerializer(
        many=True,
        required=False,
        write_only=True,
    )

    class Meta:
        model = Booking
        fields = [
            "user",
            "guest_name",
            "guest_email",
            "guest_phone",
            "item",
            "combo_pack",
            "booking_date",
            "start_time",
            "end_time",
            "total_hours",
            "subtotal",
            "discount_amount",
            "total_amount",
            "price_paid",
            "status",
            "payment_status",
            "notes",
            "is_happy_hour",
            "use_manual_loyalty_points",
            "manual_loyalty_points",
            "members",
        ]

    # ── cross-field validation ──────────────────────────────

    def validate(self, attrs):
        user = attrs.get("user")
        guest_name = attrs.get("guest_name", "").strip()
        guest_email = attrs.get("guest_email", "").strip()
        guest_phone = attrs.get("guest_phone", "")

        # Guest bookings must supply at minimum a name + email
        if not user:
            errors = {}
            if not guest_name:
                errors["guest_name"] = "Required for guest bookings."
            if not guest_email:
                errors["guest_email"] = "Required for guest bookings."
            if errors:
                raise serializers.ValidationError(errors)

        # Time sanity (model.clean() also enforces this, but catch it here
        # to return a serializer-level 400 rather than a 500)
        start_time = attrs.get("start_time")
        end_time = attrs.get("end_time")
        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError(
                {"end_time": "End time must be after start time."}
            )

        # If manual loyalty override is toggled, the points value must be present
        if (
            attrs.get("use_manual_loyalty_points")
            and attrs.get("manual_loyalty_points") is None
        ):
            raise serializers.ValidationError(
                {
                    "manual_loyalty_points": "Required when use_manual_loyalty_points is True."
                }
            )

        return attrs

    # ── create ─────────────────────────────────────────────

    def create(self, validated_data):
        members_data = validated_data.pop("members", [])

        combo_pack = validated_data.get("combo_pack")

        validated_data["created_by_admin"] = True

        # Admin manually entered loyalty points
        if validated_data.get("use_manual_loyalty_points"):
            validated_data["loyalty_points_earned"] = (
                validated_data.get("manual_loyalty_points") or 0
            )

        # Combo pack gives loyalty points
        elif combo_pack:
            validated_data["loyalty_points_earned"] = combo_pack.loyalty_bonus or 0

        booking = Booking.objects.create(**validated_data)

        for member in members_data:
            BookingMember.objects.create(
                booking=booking,
                is_admin_added=True,
                **member,
            )

        return booking


# ─────────────────────────────────────────────────────────────
# List serializer  (lightweight — used in table views)
# ─────────────────────────────────────────────────────────────


class AdminBookingListSerializer(serializers.ModelSerializer):

    customer_name = serializers.ReadOnlyField()
    customer_email = serializers.ReadOnlyField()
    customer_phone = serializers.ReadOnlyField()
    booking_type = serializers.ReadOnlyField()

    item_name = serializers.CharField(source="item.name", read_only=True)
    combo_name = serializers.SerializerMethodField()

    awarded_loyalty_points = serializers.ReadOnlyField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            "customer_name",
            "customer_email",
            "customer_phone",
            "booking_type",
            "item_name",
            "combo_name",
            "booking_date",
            "start_time",
            "end_time",
            "status",
            "payment_status",
            "total_amount",
            "price_paid",
            "is_happy_hour",
            "checked_in",
            "awarded_loyalty_points",
            "created_at",
        ]

    def get_combo_name(self, obj):
        return obj.combo_pack.name if obj.combo_pack else None


# ─────────────────────────────────────────────────────────────
# Detail serializer  (full data — used in retrieve / approve)
# ─────────────────────────────────────────────────────────────


class AdminBookingDetailSerializer(serializers.ModelSerializer):

    members = BookingMemberSerializer(many=True, read_only=True)

    customer_name = serializers.ReadOnlyField()
    customer_email = serializers.ReadOnlyField()
    customer_phone = serializers.ReadOnlyField()
    booking_type = serializers.ReadOnlyField()

    awarded_loyalty_points = serializers.SerializerMethodField()

    # Nested item / combo summaries (avoid exposing full nested objects)
    item = serializers.SerializerMethodField()
    combo_pack = serializers.SerializerMethodField()

    # QR code as absolute URL
    qr_code = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            # customer
            "user",
            "customer_name",
            "customer_email",
            "customer_phone",
            "created_by_admin",
            # item
            "item",
            "combo_pack",
            "booking_type",
            # slot
            "booking_date",
            "start_time",
            "end_time",
            "total_hours",
            # payment
            "subtotal",
            "discount_amount",
            "total_amount",
            "price_paid",
            "payment_status",
            # loyalty
            "loyalty_points_earned",
            "use_manual_loyalty_points",
            "manual_loyalty_points",
            "awarded_loyalty_points",
            # status
            "status",
            "approved_by",
            "approved_at",
            # happy hour
            "is_happy_hour",
            # QR / check-in
            "qr_token",
            "qr_code",
            "qr_sent",
            "checked_in",
            "checked_in_at",
            # misc
            "notes",
            "members",
            "created_at",
            "updated_at",
        ]

    def get_awarded_loyalty_points(self, obj):
        return obj.awarded_loyalty_points

    def get_item(self, obj):
        if not obj.item:
            return None
        return {
            "id": str(obj.item.id),
            "name": obj.item.name,
            "price_per_hour": str(obj.item.price_per_hour),
        }

    def get_combo_pack(self, obj):
        if not obj.combo_pack:
            return None
        return {
            "id": str(obj.combo_pack.id),
            "name": obj.combo_pack.name,
            "combo_price": str(obj.combo_pack.combo_price),
        }

    def get_qr_code(self, obj):
        if not obj.qr_code:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.qr_code.url)
        return obj.qr_code.url


class HappyHourTemplateSlotSerializer(serializers.ModelSerializer):

    weekday_display = serializers.CharField(
        source="get_weekday_display",
        read_only=True,
    )

    class Meta:
        model = HappyHourTemplateSlot
        fields = "__all__"


class SpinnerRewardSerializer(serializers.ModelSerializer):

    template_slot_name = serializers.CharField(
        source="template_slot.slot_name",
        read_only=True,
    )

    class Meta:
        model = SpinnerReward
        fields = "__all__"


class HappyHourBookingSerializer(serializers.ModelSerializer):

    user_name = serializers.CharField(
        source="happy_hour_slot.user.full_name",
        read_only=True,
    )

    slot_name = serializers.CharField(
        source="happy_hour_slot.template_slot.slot_name",
        read_only=True,
    )

    game_name = serializers.CharField(
        source="booking.item.name",
        read_only=True,
    )

    class Meta:
        model = HappyHourBooking
        fields = "__all__"


class AdminAssignHappyHourGameSerializer(serializers.Serializer):
    gaming_item = serializers.UUIDField()


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
        return obj.loyalty_transactions.count()

    def get_redeemed_points(self, obj):

        redeemed = obj.loyalty_transactions.filter(
            transaction_type=LoyaltyTransaction.TransactionType.REDEEMED
        ).aggregate(total=Sum("points"))

        return abs(redeemed["total"] or 0)


class AdminAdjustLoyaltySerializer(serializers.Serializer):
    points = serializers.IntegerField()

    reason = serializers.CharField()

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


from rest_framework import serializers


class AccountingSummarySerializer(serializers.Serializer):

    total_bookings = serializers.IntegerField()

    completed_bookings = serializers.IntegerField()

    cancelled_bookings = serializers.IntegerField()

    pending_bookings = serializers.IntegerField()

    gross_revenue = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    discount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    net_revenue = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    amount_received = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    pending_payment = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    average_booking = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    profit = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    loss = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )


class RevenueChartSerializer(serializers.Serializer):

    label = serializers.CharField()

    bookings = serializers.IntegerField()

    revenue = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    discount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )


class AccountingBookingSerializer(serializers.Serializer):

    booking_id = serializers.CharField()

    customer = serializers.CharField()

    booking_date = serializers.DateField()

    game = serializers.CharField()

    hours = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
    )

    subtotal = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    discount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    total = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    paid = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    payment_status = serializers.CharField()

    booking_status = serializers.CharField()


class ProfitLossSerializer(serializers.Serializer):

    gross_income = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    discounts = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    refunds = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    net_income = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    profit = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    loss = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
    )


class AccountingExportSerializer(serializers.Serializer):

    period = serializers.CharField()

    start_date = serializers.DateField(
        required=False,
    )

    end_date = serializers.DateField(
        required=False,
    )

    export_type = serializers.ChoiceField(
        choices=[
            ("pdf", "PDF"),
            ("excel", "Excel"),
        ]
    )


from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from gaming.models import CustomUser


class ProfileSerializer(serializers.ModelSerializer):

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


from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password

from gaming.models import (
    CustomUser,
    PasswordResetOTP,
)


class ForgotPasswordSerializer(serializers.Serializer):

    email = serializers.EmailField()

    def validate_email(self, value):

        if not CustomUser.objects.filter(
            email=value,
            is_active=True,
        ).exists():

            raise serializers.ValidationError("No account found with this email.")

        return value


class VerifyForgotOTPSerializer(serializers.Serializer):

    email = serializers.EmailField()

    otp = serializers.CharField(
        max_length=6,
    )


class ResetPasswordSerializer(serializers.Serializer):

    email = serializers.EmailField()

    otp = serializers.CharField(
        max_length=6,
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


class UserGameCategorySerializer(serializers.ModelSerializer):

    image = serializers.SerializerMethodField()

    class Meta:
        model = GameCategory
        fields = [
            "id",
            "name",
            "category_type",
            "image",
        ]

    def get_image(self, obj):
        request = self.context.get("request")
        if obj.image:
            return request.build_absolute_uri(obj.image.url)
        return None


class UserGamingItemListSerializer(serializers.ModelSerializer):

    image = serializers.SerializerMethodField()

    category = serializers.CharField(source="category.name", read_only=True)

    category_id = serializers.UUIDField(source="category.id", read_only=True)

    class Meta:
        model = GamingItem
        fields = [
            "id",
            "name",
            "category",
            "category_id",
            "description",
            "image",
            "price_per_hour",
            "min_capacity",
            "max_capacity",
            "maintenance_mode",
        ]

    def get_image(self, obj):
        request = self.context.get("request")
        if obj.image:
            return request.build_absolute_uri(obj.image.url)
        return None


class UserGamingItemDetailSerializer(serializers.ModelSerializer):

    image = serializers.SerializerMethodField()

    category = UserGameCategorySerializer(read_only=True)

    class Meta:
        model = GamingItem
        fields = [
            "id",
            "name",
            "description",
            "image",
            "category",
            "price_per_hour",
            "min_capacity",
            "max_capacity",
            "maintenance_mode",
            "created_at",
        ]

    def get_image(self, obj):
        request = self.context.get("request")
        if obj.image:
            return request.build_absolute_uri(obj.image.url)
        return None


class BookingMemberSerializer(serializers.ModelSerializer):  # duplicate

    class Meta:
        model = BookingMember
        fields = [
            "id",
            "name",
            "phone",
            "is_admin_added",
        ]


from datetime import datetime
from decimal import Decimal
from rest_framework import serializers
from django.db import transaction


class BookingCreateSerializer(serializers.ModelSerializer):

    members = BookingMemberSerializer(many=True, required=False)

    class Meta:
        model = Booking
        fields = [
            "item",
            "booking_date",
            "start_time",
            "end_time",
            "members",
            "notes",
        ]

    def validate(self, attrs):

        item = attrs["item"]

        booking_date = attrs["booking_date"]
        start_time = attrs["start_time"]
        end_time = attrs["end_time"]

        members = self.initial_data.get("members", [])

        if item.maintenance_mode:
            raise serializers.ValidationError(
                "This game is currently under maintenance."
            )

        if start_time >= end_time:
            raise serializers.ValidationError("End time must be after start time.")

        overlapping = Booking.objects.filter(
            item=item,
            booking_date=booking_date,
            start_time__lt=end_time,
            end_time__gt=start_time,
            status__in=[
                Booking.Status.PENDING,
                Booking.Status.CONFIRMED,
            ],
        )
        occupied_people = 0
        for booking in overlapping:

            occupied_people += 1  # booking owner

            occupied_people += booking.total_people

        new_people = len(members) + 1

        if occupied_people + new_people > item.max_capacity:

            raise serializers.ValidationError(
                {
                    "message": "This slot is not available. Maximum player limit has been reached."
                }
            )
        if overlapping.exists():

            raise serializers.ValidationError(
                {"message": "This slot is already booked."}
            )

        total_people = len(members) + 1

        if total_people < item.min_capacity:
            raise serializers.ValidationError(
                f"This game requires at least {item.min_capacity} player(s)."
            )

        if total_people > item.max_capacity:
            raise serializers.ValidationError(
                f"Maximum {item.max_capacity} players allowed."
            )

        start = datetime.combine(booking_date, start_time)
        end = datetime.combine(booking_date, end_time)

        hours = Decimal(str((end - start).total_seconds() / 3600))

        attrs["total_hours"] = hours
        attrs["subtotal"] = hours * item.price_per_hour
        attrs["discount_amount"] = 0
        attrs["total_amount"] = attrs["subtotal"]

        return attrs

    @transaction.atomic
    def create(self, validated_data):

        members = validated_data.pop("members", [])

        booking = Booking.objects.create(
            user=self.context["request"].user,
            total_hours=validated_data.pop("total_hours"),
            subtotal=validated_data.pop("subtotal"),
            discount_amount=validated_data.pop("discount_amount"),
            total_amount=validated_data.pop("total_amount"),
            loyalty_points_earned=10,
            **validated_data,
        )

        for member in members:

            BookingMember.objects.create(
                booking=booking,
                name=member["name"],
                phone=member.get("phone", ""),
            )
        user = booking.user
        user.loyalty_points += 10
        user.save(update_fields=["loyalty_points"])
        LoyaltyTransaction.objects.create(
            user=user,
            booking=booking,
            points=10,
            transaction_type=LoyaltyTransaction.TransactionType.EARNED,
            description=f"10 loyalty points earned for booking {booking.booking_id}",
        )

        return booking


class BookingListSerializer(serializers.ModelSerializer):

    game_name = serializers.SerializerMethodField()
    game_image = serializers.SerializerMethodField()
    total_people = serializers.ReadOnlyField()
    can_check_in = serializers.ReadOnlyField()
    is_qr_valid = serializers.ReadOnlyField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            "game_name",
            "game_image",
            "booking_date",
            "start_time",
            "end_time",
            "status",
            "payment_status",
            "total_amount",
            "total_people",
            "can_check_in",
            "is_qr_valid",
        ]

    def get_game_name(self, obj):

        if obj.item:
            return obj.item.name

        if obj.combo_pack:
            return obj.combo_pack.name

        return None

    def get_game_image(self, obj):

        request = self.context.get("request")

        image = None

        if obj.item:
            image = obj.item.image

        elif obj.combo_pack:
            image = obj.combo_pack.image

        if image:
            return request.build_absolute_uri(image.url)

        return None


class BookingDetailSerializer(serializers.ModelSerializer):

    members = BookingMemberSerializer(many=True, read_only=True)

    game = UserGamingItemDetailSerializer(source="item", read_only=True)

    customer_name = serializers.ReadOnlyField()
    customer_email = serializers.ReadOnlyField()
    customer_phone = serializers.ReadOnlyField()

    total_people = serializers.ReadOnlyField()

    booking_type = serializers.ReadOnlyField()

    awarded_loyalty_points = serializers.ReadOnlyField()

    can_check_in = serializers.ReadOnlyField()

    is_qr_valid = serializers.ReadOnlyField()

    approved_by_name = serializers.SerializerMethodField()

    qr_code = serializers.SerializerMethodField()

    class Meta:
        model = Booking

        fields = [
            "id",
            "booking_id",
            "booking_type",
            "game",
            "customer_name",
            "customer_email",
            "customer_phone",
            "booking_date",
            "start_time",
            "end_time",
            "total_hours",
            "subtotal",
            "discount_amount",
            "total_amount",
            "price_paid",
            "status",
            "payment_status",
            "notes",
            "members",
            "total_people",
            "loyalty_points_earned",
            "awarded_loyalty_points",
            "approved_by_name",
            "approved_at",
            "qr_token",
            "qr_code",
            "checked_in",
            "checked_in_at",
            "can_check_in",
            "is_qr_valid",
            "created_at",
        ]

    def get_approved_by_name(self, obj):

        if obj.approved_by:
            return obj.approved_by.full_name

        return None

    def get_qr_code(self, obj):

        request = self.context.get("request")

        if obj.qr_code:
            return request.build_absolute_uri(obj.qr_code.url)

        return None


class BookingHistorySerializer(serializers.ModelSerializer):

    game_name = serializers.SerializerMethodField()

    class Meta:
        model = Booking

        fields = [
            "id",
            "booking_id",
            "game_name",
            "booking_date",
            "start_time",
            "end_time",
            "status",
            "payment_status",
            "total_amount",
            "loyalty_points_earned",
            "created_at",
        ]

    def get_game_name(self, obj):

        if obj.item:
            return obj.item.name

        if obj.combo_pack:
            return obj.combo_pack.name

        return None


from rest_framework import serializers


class AvailableSlotSerializer(serializers.Serializer):
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    available = serializers.BooleanField()


# ----------------------------------- Home --------------------------------------


class HomeBannerSerializer(serializers.Serializer):

    id = serializers.UUIDField()

    title = serializers.CharField()

    subtitle = serializers.CharField()

    image = serializers.ImageField()

    type = serializers.CharField()

    action_url = serializers.CharField()


class HomeEventSerializer(serializers.ModelSerializer):

    available_slots = serializers.ReadOnlyField()
    image = serializers.SerializerMethodField()

    class Meta:

        model = ExclusiveEvent

        fields = (
            "id",
            "title",
            "description",
            "event_date",
            "start_time",
            "end_time",
            "price",
            "available_slots",
            "image",
        )

    def get_image(self, obj):

        if not obj.image:
            return None

        request = self.context.get("request")

        if request:
            return request.build_absolute_uri(obj.image.url)

        return obj.image.url


class HomeComboSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:

        model = ComboPack

        fields = (
            "id",
            "name",
            "combo_price",
            "snack_name",
            "image",
            "loyalty_bonus",
        )

    def get_image(self, obj):

        if not obj.image:
            return None

        request = self.context.get("request")

        if request:
            return request.build_absolute_uri(obj.image.url)

        return obj.image.url


class HomeGameSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:

        model = GamingItem

        fields = (
            "id",
            "name",
            "image",
            "price_per_hour",
            "max_capacity",
            "maintenance_mode",
        )

    def get_image(self, obj):

        if not obj.image:
            return None

        request = self.context.get("request")

        if request:
            return request.build_absolute_uri(obj.image.url)

        return obj.image.url


class HomeCategorySerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    games = HomeGameSerializer(
        source="gaming_items",
        many=True,
    )

    class Meta:

        model = GameCategory

        fields = (
            "id",
            "name",
            "category_type",
            "image",
            "games",
        )

    def get_image(self, obj):

        if not obj.image:
            return None

        request = self.context.get("request")

        if request:
            return request.build_absolute_uri(obj.image.url)

        return obj.image.url


class HomeStatsSerializer(serializers.Serializer):

    total_users = serializers.IntegerField()

    total_games = serializers.IntegerField()

    total_events = serializers.IntegerField()

    total_combo_packs = serializers.IntegerField()


class HomeSerializer(serializers.Serializer):

    banners = serializers.ListField()

    events = HomeEventSerializer(many=True)

    combo_packs = HomeComboSerializer(many=True)

    categories = HomeCategorySerializer(many=True)

    stats = HomeStatsSerializer()


from django.utils import timezone
from rest_framework import serializers

from .models import Booking, BookingMember, EventBooking


class UserBookingMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingMember
        fields = ["id", "name", "phone", "is_admin_added"]


class UserBookingWalletSerializer(serializers.ModelSerializer):
    booking_kind = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    members = UserBookingMemberSerializer(many=True, read_only=True)
    qr_code_url = serializers.SerializerMethodField()
    qr_token = serializers.UUIDField(read_only=True)
    is_qr_valid = serializers.BooleanField(read_only=True)
    can_cancel = serializers.SerializerMethodField()
    starts_at = serializers.SerializerMethodField()
    ends_at = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            "booking_kind",
            "title",
            "image",
            "category",
            "booking_date",
            "start_time",
            "end_time",
            "starts_at",
            "ends_at",
            "total_hours",
            "subtotal",
            "discount_amount",
            "total_amount",
            "price_paid",
            "payment_status",
            "status",
            "loyalty_points_earned",
            "total_people",
            "members",
            "qr_code_url",
            "qr_token",
            "qr_sent",
            "is_qr_valid",
            "checked_in",
            "checked_in_at",
            "can_cancel",
            "cancelled_at",
            "cancellation_reason",
            "refund_amount",
            "refund_status",
            "notes",
            "created_at",
        ]

    def get_booking_kind(self, obj):
        return "combo" if obj.combo_pack_id else "booking"

    def get_title(self, obj):
        if obj.combo_pack:
            return obj.combo_pack.name
        if obj.item:
            return obj.item.name
        return "Booking"

    def get_image(self, obj):
        image = None
        if obj.combo_pack and obj.combo_pack.image:
            image = obj.combo_pack.image
        elif obj.item and obj.item.image:
            image = obj.item.image
        return self._absolute_media_url(image)

    def get_category(self, obj):
        if obj.item and obj.item.category:
            return obj.item.category.name
        if obj.combo_pack:
            return "Combo"
        return ""

    def get_qr_code_url(self, obj):
        return self._absolute_media_url(obj.qr_code)

    def get_can_cancel(self, obj):
        if obj.status in [Booking.Status.CANCELLED, Booking.Status.COMPLETED]:
            return False
        booking_start = timezone.make_aware(
            timezone.datetime.combine(obj.booking_date, obj.start_time)
        )
        return timezone.now() < booking_start

    def get_starts_at(self, obj):
        return timezone.make_aware(
            timezone.datetime.combine(obj.booking_date, obj.start_time)
        ).isoformat()

    def get_ends_at(self, obj):
        return timezone.make_aware(
            timezone.datetime.combine(obj.booking_date, obj.end_time)
        ).isoformat()

    def _absolute_media_url(self, file_field):
        if not file_field:
            return None
        request = self.context.get("request")
        url = file_field.url
        return request.build_absolute_uri(url) if request else url


class UserEventBookingWalletSerializer(serializers.ModelSerializer):
    booking_kind = serializers.SerializerMethodField()
    title = serializers.CharField(source="event.title", read_only=True)
    image = serializers.SerializerMethodField()
    booking_date = serializers.DateField(source="event.event_date", read_only=True)
    start_time = serializers.TimeField(source="event.start_time", read_only=True)
    end_time = serializers.TimeField(source="event.end_time", read_only=True)
    starts_at = serializers.SerializerMethodField()
    ends_at = serializers.SerializerMethodField()
    total_amount = serializers.DecimalField(
        source="event.price", max_digits=10, decimal_places=2, read_only=True
    )
    price_paid = serializers.DecimalField(
        source="amount_paid", max_digits=10, decimal_places=2, read_only=True
    )
    payment_status = serializers.SerializerMethodField()
    qr_code_url = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()
    total_people = serializers.SerializerMethodField()

    class Meta:
        model = EventBooking
        fields = [
            "id",
            "booking_id",
            "booking_kind",
            "title",
            "image",
            "booking_date",
            "start_time",
            "end_time",
            "starts_at",
            "ends_at",
            "total_amount",
            "price_paid",
            "payment_status",
            "status",
            "total_people",
            "members",
            "qr_code_url",
            "qr_token",
            "qr_sent",
            "checked_in",
            "checked_in_at",
            "can_cancel",
            "notes",
            "created_at",
        ]

    def get_booking_kind(self, obj):
        return "event"

    def get_image(self, obj):
        if not obj.event.image:
            return None
        request = self.context.get("request")
        url = obj.event.image.url
        return request.build_absolute_uri(url) if request else url

    def get_starts_at(self, obj):
        return timezone.make_aware(
            timezone.datetime.combine(obj.event.event_date, obj.event.start_time)
        ).isoformat()

    def get_ends_at(self, obj):
        return timezone.make_aware(
            timezone.datetime.combine(obj.event.event_date, obj.event.end_time)
        ).isoformat()

    def get_payment_status(self, obj):
        return "paid" if obj.amount_paid and obj.amount_paid > 0 else "pending"

    def get_qr_code_url(self, obj):
        if not obj.qr_code:
            return None
        request = self.context.get("request")
        url = obj.qr_code.url
        return request.build_absolute_uri(url) if request else url

    def get_can_cancel(self, obj):
        if obj.status in [EventBooking.Status.CANCELLED, EventBooking.Status.ATTENDED]:
            return False
        event_start = timezone.make_aware(
            timezone.datetime.combine(obj.event.event_date, obj.event.start_time)
        )
        return timezone.now() < event_start

    def get_members(self, obj):
        return []

    def get_total_people(self, obj):
        return 1


class CancelBookingSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)
























from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from gaming.models import Booking, GamingItem, LoyaltyTransaction



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










class UserGamingItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = GamingItem
        fields = [
            "id",
            "name",
            "description",
            "image",
            "image_url",
            "price_per_hour",
            "min_capacity",
            "max_capacity",
            "category",
            "category_name",
        ]

    def get_image_url(self, obj):
        request = self.context.get("request")

        if not obj.image:
            return None

        if request:
            return request.build_absolute_uri(obj.image.url)

        return obj.image.url




from rest_framework import serializers

class AvailableSlotSerializer(serializers.Serializer):
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    available = serializers.BooleanField()











class UpcomingEventSerializer(serializers.ModelSerializer):
    available_slots = serializers.ReadOnlyField()

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


from django.conf import settings

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

        if not obj.event.image:
            return None

        request = self.context.get("request")

        if request:
            return request.build_absolute_uri(obj.event.image.url)

        return f"{settings.SITE_URL.rstrip('/')}{obj.event.image.url}"

    def get_qr_code(self, obj):

        if not obj.qr_code:
            return None

        request = self.context.get("request")

        if request:
            return request.build_absolute_uri(obj.qr_code.url)

        return f"{settings.SITE_URL.rstrip('/')}{obj.qr_code.url}"
    

    

class CreateEventBookingSerializer(serializers.ModelSerializer):

    class Meta:
        model = EventBooking
        fields = []










from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from gaming.models import Booking, BookingMember, ComboPack


def absolute_media_url(request, file_field):
    if not file_field:
        return None
    try:
        url = file_field.url
    except ValueError:
        return None
    if request:
        return request.build_absolute_uri(url)
    site_url = getattr(settings, "SITE_URL", "").rstrip("/")
    return f"{site_url}{url}" if site_url else url


def combo_price(obj):
    return getattr(obj, "combo_price", getattr(obj, "price", None))


def combo_max_people(obj):
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


class ComboGamingItemSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True, required=False)
    image = serializers.SerializerMethodField()

    def get_image(self, obj):
        return absolute_media_url(self.context.get("request"), getattr(obj, "image", None))


class BookingComboMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingMember
        fields = ["id", "name", "phone"]
        read_only_fields = ["id"]


class UserComboPackSerializer(serializers.ModelSerializer):
    description = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    combo_price = serializers.SerializerMethodField()
    snack_name = serializers.SerializerMethodField()
    snack_price = serializers.SerializerMethodField()
    loyalty_bonus = serializers.SerializerMethodField()
    max_people = serializers.SerializerMethodField()
    gaming_items = serializers.SerializerMethodField()

    class Meta:
        model = ComboPack
        fields = [
            "id",
            "name",
            "description",
            "combo_price",
            "snack_name",
            "snack_price",
            "loyalty_bonus",
            "max_people",
            "gaming_items",
            "image",
        ]

    def get_image(self, obj):
        return absolute_media_url(self.context.get("request"), getattr(obj, "image", None))

    def get_combo_price(self, obj):
        return combo_price(obj)

    def get_snack_name(self, obj):
        return getattr(obj, "snack_name", None)

    def get_snack_price(self, obj):
        return getattr(obj, "snack_price", None)

    def get_loyalty_bonus(self, obj):
        return getattr(obj, "loyalty_bonus", 0)

    def get_gaming_items(self, obj):
        manager = getattr(obj, "gaming_items", None) or getattr(obj, "items", None)
        if not manager:
            return []
        items = manager.all() if hasattr(manager, "all") else manager
        return ComboGamingItemSerializer(items, many=True, context=self.context).data
    
    def get_description(self, obj):
        for field_name in ("description", "details", "short_description"):
            value = getattr(obj, field_name, None)
            if value:
                return value
        return ""
    
    def get_max_people(self, obj):
        return combo_max_people(obj)



class UserComboPackDetailSerializer(UserComboPackSerializer):
    pass


class CreateComboBookingSerializer(serializers.Serializer):
    combo_pack = serializers.UUIDField()
    booking_date = serializers.DateField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    members = BookingComboMemberSerializer(many=True, required=False, allow_empty=True)

    def validate(self, attrs):
        combo = ComboPack.objects.filter(
            id=attrs["combo_pack"],
            is_active=True,
            is_deleted=False,
        ).first()
        if not combo:
            raise serializers.ValidationError({"combo_pack": "Active combo pack not found."})

        today = timezone.localdate()
        if attrs["booking_date"] < today:
            raise serializers.ValidationError({"booking_date": "Booking date cannot be in the past."})

        if attrs["end_time"] <= attrs["start_time"]:
            raise serializers.ValidationError({"end_time": "End time must be after start time."})

        members = attrs.get("members", [])
        total_people = len(members) + 1
        max_people = combo_max_people(combo)
        if total_people > max_people:
            raise serializers.ValidationError({"members": f"Maximum {max_people} people allowed."})

        attrs["combo"] = combo
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        combo = validated_data["combo"]
        members = validated_data.get("members", [])
        total_price = combo_price(combo) or Decimal("0.00")
        start_time = validated_data["start_time"]
        end_time = validated_data["end_time"]
        start_seconds = start_time.hour * 3600 + start_time.minute * 60 + start_time.second
        end_seconds = end_time.hour * 3600 + end_time.minute * 60 + end_time.second
        total_hours = round((end_seconds - start_seconds) / 3600, 2)
        booking = Booking.objects.create(
            user=request.user,
            combo_pack=combo,
            booking_date=validated_data["booking_date"],
            start_time=start_time,
            end_time=end_time,
            total_hours=total_hours,
            subtotal=total_price,
            discount_amount=Decimal("0.00"),
            total_amount=total_price,
            price_paid=Decimal("0.00"),
            status=getattr(getattr(Booking, "Status", object), "PENDING", "PENDING"),
        )
        BookingMember.objects.bulk_create(
            [BookingMember(booking=booking, name=m["name"], phone=m["phone"]) for m in members]
        )
        return booking


class UserComboBookingSerializer(serializers.ModelSerializer):
    combo_name = serializers.CharField(source="combo_pack.name", read_only=True)
    combo_image = serializers.SerializerMethodField()
    qr_code = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()
    members = BookingComboMemberSerializer(many=True, read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_id",
            "combo_name",
            "combo_image",
            "booking_date",
            "start_time",
            "end_time",
            "status",
            "total_amount",
            "member_count",
            "members",
            "qr_code",
            "qr_token",
            "checked_in",
            "checked_in_at",
            "created_at",
        ]

    def get_combo_image(self, obj):
        return absolute_media_url(self.context.get("request"), getattr(obj.combo_pack, "image", None))

    def get_qr_code(self, obj):
        return absolute_media_url(self.context.get("request"), getattr(obj, "qr_code", None))

    def get_member_count(self, obj):
        prefetched = getattr(obj, "_prefetched_objects_cache", {})
        if "members" in prefetched:
            return len(prefetched["members"]) + 1
        return obj.members.count() + 1



from gaming.models import TermsAndConditions

class TermsSerializer(serializers.ModelSerializer):

    class Meta:
        model = TermsAndConditions
        fields = (
            "id",
            "version",
            "title",
            "content",
            "effective_date",
        )




from rest_framework import serializers
from gaming.models import HappyHourAllocation


class HappyHourAllocationSerializer(serializers.ModelSerializer):

    class Meta:
        model = HappyHourAllocation
        fields = [
            "id",
            "date",
            "start_time",
            "end_time",
            "offer_percentage",
            "loyalty_points",
            "is_free",
            "max_bookings",
            "is_active",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):

        start_time = attrs.get(
            "start_time",
            getattr(self.instance, "start_time", None)
        )

        end_time = attrs.get(
            "end_time",
            getattr(self.instance, "end_time", None)
        )

        offer_percentage = attrs.get(
            "offer_percentage",
            getattr(self.instance, "offer_percentage", 0)
        )

        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError({
                "end_time": "End time must be after start time."
            })

        if offer_percentage > 100:
            raise serializers.ValidationError({
                "offer_percentage": "Offer percentage cannot exceed 100."
            })

        return attrs
    

class UserHappyHourAllocationSerializer(serializers.ModelSerializer):

    class Meta:
        model = HappyHourAllocation
        fields = [
            "id",
            "date",
            "start_time",
            "end_time",
            "offer_percentage",
            "is_free",
            "max_bookings",
            "is_active",
            "notes",
        ]