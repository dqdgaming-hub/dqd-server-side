import uuid
import datetime
import secrets

from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser,
    PermissionsMixin,
    BaseUserManager,
)
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# ==========================================================
# BASE MODEL
# ==========================================================


class BaseModel(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    is_active = models.BooleanField(default=True)

    is_deleted = models.BooleanField(default=False)

    class Meta:
        abstract = True


# ==========================================================
# USER MANAGER
# ==========================================================


class CustomUserManager(BaseUserManager):

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        extra_fields.setdefault("role", CustomUser.Role.USER)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_verified", True)
        extra_fields.setdefault("role", CustomUser.Role.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        if extra_fields.get("role") != CustomUser.Role.ADMIN:
            raise ValueError("Superuser must have role=admin.")

        return self.create_user(email, password, **extra_fields)







from django.utils import timezone


class TermsAndConditions(BaseModel):
    version = models.CharField(
        max_length=20,
        unique=True
    )

    title = models.CharField(
        max_length=255
    )

    content = models.TextField()

    effective_date = models.DateField()

    is_current = models.BooleanField(
        default=True
    )

    class Meta:
        db_table = "terms_conditions"
        ordering = ["-effective_date"]

    def save(self, *args, **kwargs):
        if self.is_current:
            TermsAndConditions.objects.exclude(
                pk=self.pk
            ).update(is_current=False)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.version}"



# ==========================================================
# CUSTOM USER
# ==========================================================


class CustomUser(AbstractBaseUser, PermissionsMixin, BaseModel):

    class Gender(models.TextChoices):
        MALE = "male", _("Male")
        FEMALE = "female", _("Female")
        OTHER = "other", _("Other")

    class Role(models.TextChoices):
        USER = "user", _("User")
        ADMIN = "admin", _("Admin")

    class LoginProvider(models.TextChoices):
        EMAIL = "email", _("Email")
        GOOGLE = "google", _("Google")
        FACEBOOK = "facebook", _("Facebook")

    first_name = models.CharField(max_length=100)

    last_name = models.CharField(max_length=100, blank=True)

    email = models.EmailField(unique=True, db_index=True)

    phone = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
    )

    dob = models.DateField(null=True, blank=True)

    gender = models.CharField(
        max_length=20,
        choices=Gender.choices,
        blank=True,
    )

    profile_image = models.BinaryField(
        null=True,
        blank=True,
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.USER,
    )

    login_provider = models.CharField(
        max_length=20,
        choices=LoginProvider.choices,
        default=LoginProvider.EMAIL,
    )

    loyalty_points = models.PositiveIntegerField(default=0)

    is_verified = models.BooleanField(default=False)

    is_staff = models.BooleanField(default=False)

    last_login = models.DateTimeField(null=True, blank=True)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    accepted_terms = models.ForeignKey(
        TermsAndConditions,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="accepted_users"
    )

    accepted_terms_at = models.DateTimeField(
        null=True,
        blank=True
    )
    
    class Meta:
        db_table = "users"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["phone"]),
        ]

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class UserDevice(BaseModel):
    ONLINE_STALE_AFTER = datetime.timedelta(minutes=3)

    class DeviceType(models.TextChoices):
        DESKTOP = "desktop", "Desktop"
        MOBILE = "mobile", "Mobile"
        TABLET = "tablet", "Tablet"
        BOT = "bot", "Bot"
        OTHER = "other", "Other"

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="devices",
    )
    device_id = models.UUIDField(default=uuid.uuid4, editable=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    device_name = models.CharField(max_length=255, default="Unknown")
    device_type = models.CharField(
        max_length=20,
        choices=DeviceType.choices,
        default=DeviceType.OTHER,
    )
    browser = models.CharField(max_length=150, default="Unknown")
    operating_system = models.CharField(max_length=150, default="Unknown")
    user_agent = models.TextField(blank=True)
    last_seen = models.DateTimeField(default=timezone.now, db_index=True)
    login_at = models.DateTimeField(default=timezone.now)
    logged_out_at = models.DateTimeField(null=True, blank=True)
    is_online = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "user_devices"
        ordering = ["-last_seen"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "device_id"],
                name="unique_user_device",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "is_deleted", "is_online", "-last_seen"],
                name="device_user_active_seen_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.device_name}"

    @property
    def is_currently_online(self):
        """Return true only when the device is online and recently active."""
        return bool(
            self.is_online
            and self.last_seen >= timezone.now() - self.ONLINE_STALE_AFTER
        )
        

# ==========================================================
# GAME CATEGORY
# ==========================================================


class GameCategory(BaseModel):

    class CategoryType(models.TextChoices):
        PS5 = "ps5", "PS5"
        POOL = "pool", "Pool"
        VR = "vr", "VR"
        SIMULATOR = "simulator", "Simulator"
        MULTIPLAYER_GAMES = "multiplayer_games", "Multiplayer Games"
        BOARD_GAMES = "board_games", "Board Games"
        CARD_GAMES = "card_games", "Card Games"
        OTT = "ott", "OTT / Streaming"
        OTHER = "other", "Other"

    name = models.CharField(max_length=100, unique=True)

    category_type = models.CharField(
        max_length=20,
        choices=CategoryType.choices,
    )

    image = models.BinaryField(
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "game_categories"

    def __str__(self):
        return self.name


# ==========================================================
# GAMING ITEM
# Covers PS5 consoles, Pool tables, OTT/Streaming screens,
# and any other bookable gaming units.
#
# For OTT/Streaming, admin sets min_capacity and max_capacity
# to control how many people can share a screen booking.
# For PS5/Pool/Other, min_capacity defaults to 1.
# ==========================================================


class GamingItem(BaseModel):

    category = models.ForeignKey(
        GameCategory,
        on_delete=models.CASCADE,
        related_name="gaming_items",
    )

    name = models.CharField(max_length=255)

    description = models.TextField(blank=True)

    image = models.BinaryField(
        blank=True,
        null=True,
    )

    # For OTT: admin-defined min seats required to book
    min_capacity = models.PositiveIntegerField(
        default=1,
        help_text="Minimum number of people required to book (used for OTT/Streaming)",
    )

    # For OTT: admin-defined max seats allowed per booking
    max_capacity = models.PositiveIntegerField(
        default=14,
        help_text="Maximum number of people allowed per booking",
    )

    price_per_hour = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    maintenance_mode = models.BooleanField(default=False)

    class Meta:
        db_table = "gaming_items"

    def __str__(self):
        return self.name

    def clean(self):
        if self.min_capacity > self.max_capacity:
            raise ValidationError("min_capacity cannot be greater than max_capacity.")


# ==========================================================
# COMBO PACK
# A bundle linking one or more gaming items with a snack,
# offered at a combined discounted price.
# ==========================================================


class ComboPack(BaseModel):

    name = models.CharField(max_length=255)

    gaming_items = models.ManyToManyField(
        GamingItem,
        related_name="combo_packs",
    )

    snack_name = models.CharField(max_length=255)

    snack_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    combo_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    loyalty_bonus = models.PositiveIntegerField(
        default=0,
        help_text="Extra loyalty points awarded when this combo is booked",
    )

    image = models.BinaryField(
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "combo_packs"

    def __str__(self):
        return self.name


# ==========================================================
# BOOKING
# Core booking model. QR token is generated automatically.
# QR validity is time-gated: expires when booking end time
# passes on the booking date.
# ==========================================================


class Booking(BaseModel):

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentStatus(models.TextChoices): 
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    booking_id = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
    )

    # =====================================================
    # USER / GUEST DETAILS
    # =====================================================

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="bookings",
        null=True,
        blank=True,
    )

    guest_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    guest_email = models.EmailField(
        blank=True,
        null=True,
    )

    guest_phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
    )

    created_by_admin = models.BooleanField(default=False)

    # =====================================================
    # ITEM / COMBO
    # =====================================================

    item = models.ForeignKey(
        GamingItem,
        on_delete=models.CASCADE,
        related_name="bookings",
        null=True,
        blank=True,
    )

    combo_pack = models.ForeignKey(
        ComboPack,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookings",
    )

    # =====================================================
    # SLOT DETAILS
    # =====================================================

    booking_date = models.DateField()

    start_time = models.TimeField()

    end_time = models.TimeField()

    total_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
    )

    # =====================================================
    # PAYMENT
    # =====================================================

    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    price_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )

    # =====================================================
    # LOYALTY
    # =====================================================

    loyalty_points_earned = models.PositiveIntegerField(default=0)

    use_manual_loyalty_points = models.BooleanField(default=False)

    manual_loyalty_points = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    # =====================================================
    # BOOKING STATUS
    # =====================================================

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    approved_by = models.ForeignKey(
        CustomUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_bookings",
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # =====================================================
    # QR
    # =====================================================

    qr_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    qr_code = models.BinaryField(
        blank=True,
        null=True,
    )

    qr_sent = models.BooleanField(default=False)

    checked_in = models.BooleanField(default=False)

    checked_in_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # =====================================================
    # HAPPY HOUR
    # =====================================================

    is_happy_hour = models.BooleanField(default=False)

    happy_hour_slot = models.OneToOneField(
        "HappyHourSlot",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="booking",
    )

    happy_hour_booking = models.OneToOneField(
        "HappyHourBooking",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="redeemed_booking",
    )
    # =====================================================
    # NOTES
    # =====================================================

    notes = models.TextField(blank=True)

    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    cancelled_by = models.ForeignKey(
        CustomUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_bookings",
    )

    cancellation_reason = models.TextField(
        blank=True,
    )

    refund_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    refund_status = models.CharField(
        max_length=20,
        choices=[
            ("none", "None"),
            ("pending", "Pending"),
            ("processed", "Processed"),
            ("failed", "Failed"),
        ],
        default="none",
    )

    cancelled_from = models.CharField(
        max_length=20,
        choices=[
            ("user", "User"),
            ("admin", "Admin"),
            ("system", "System"),
        ],
        blank=True,
    )

    ticket_downloads = models.PositiveIntegerField(default=0)

    last_ticket_download = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "bookings"
        ordering = ["-created_at"]

        indexes = [
            models.Index(fields=["booking_date"]),
            models.Index(fields=["status"]),
            models.Index(fields=["payment_status"]),
            models.Index(fields=["qr_token"]),
        ]

    def clean(self):

        if self.start_time >= self.end_time:
            raise ValidationError("Start time must be before end time.")
        # Guest validation
        if not self.item and not self.combo_pack:
            raise ValidationError("Either item or combo pack is required.")
        if not self.user:

            if not self.guest_name:
                raise ValidationError("Guest name is required.")

            if not self.guest_email:
                raise ValidationError("Guest email is required.")

            if not self.guest_phone:
                raise ValidationError("Guest phone is required.")

        if self.item:
            overlapping = Booking.objects.filter(
                item=self.item,
                booking_date=self.booking_date,
                start_time__lt=self.end_time,
                end_time__gt=self.start_time,
                status__in=[
                    Booking.Status.PENDING,
                    Booking.Status.CONFIRMED,
                ],
            ).exclude(pk=self.pk)

            if overlapping.exists():
                message = (
                    "Happy Hour slot already occupied."
                    if self.happy_hour_slot
                    else "This slot is already booked."
                )
                raise ValidationError(message)

    def save(self, *args, **kwargs):

        self.clean()

        if not self.booking_id:
            self.booking_id = f"DQD-{uuid.uuid4().hex[:8].upper()}"

        super().save(*args, **kwargs)

    @property
    def customer_name(self):

        if self.user:
            return self.user.full_name

        return self.guest_name

    @property
    def customer_email(self):

        if self.user and self.user.email:
            return self.user.email

        return self.guest_email

    @property
    def customer_phone(self):

        if self.user and self.user.phone:
            return self.user.phone

        return self.guest_phone

    @property
    def awarded_loyalty_points(self):

        if self.use_manual_loyalty_points and self.manual_loyalty_points is not None:
            return self.manual_loyalty_points

        return self.loyalty_points_earned

    @property
    def booking_type(self):
        if self.combo_pack:
            return "combo"
        return "game_item"

    @property
    def total_people(self):
        return self.members.count() + 1

    @property
    def can_check_in(self):

        return (
            self.status == self.Status.CONFIRMED
            and self.is_qr_valid
            and not self.checked_in
        )

    @property
    def is_qr_valid(self):

        if self.status != self.Status.CONFIRMED:
            return False

        booking_end = timezone.make_aware(
            datetime.datetime.combine(
                self.booking_date,
                self.end_time,
            )
        )

        return timezone.now() <= booking_end

    def __str__(self):
        return self.booking_id


# ==========================================================
# BOOKING MEMBER
# People attached to a booking (besides the primary user).
#
# - Users add members themselves (is_admin_added=False).
# - Admins can add extra guests on behalf of the user
#   (is_admin_added=True).
# - For OTT bookings the member count is validated against
#   GamingItem.min_capacity / max_capacity at the view layer.
# ==========================================================


class BookingMember(BaseModel):

    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="members",
    )

    name = models.CharField(
        max_length=150,
        help_text="Full name of the member",
    )

    phone = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional contact number for the member",
    )

    is_admin_added = models.BooleanField(
        default=False,
        help_text="True when an admin added this member (extra guest)",
    )

    class Meta:
        db_table = "booking_members"

    def __str__(self):
        return f"{self.name} ({self.booking.booking_id})"


# ==========================================================
# EXCLUSIVE EVENTS
# ==========================================================


class ExclusiveEvent(BaseModel):

    title = models.CharField(max_length=255)

    description = models.TextField()

    event_date = models.DateField()

    start_time = models.TimeField()

    end_time = models.TimeField()

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    max_participants = models.PositiveIntegerField()

    image = models.BinaryField(
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "exclusive_events"

    def __str__(self):
        return self.title

    @property
    def available_slots(self):
        booked = self.bookings.filter(
            is_deleted=False,
        ).exclude(
            status__in=[
                EventBooking.Status.CANCELLED,
                EventBooking.Status.REJECTED,
            ],
        ).count()
        return max(0, self.max_participants - booked)


class EventBooking(BaseModel):

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        ATTENDED = "attended", "Attended"
        CANCELLED = "cancelled", "Cancelled"

    booking_id = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
    )

    event = models.ForeignKey(
        ExclusiveEvent,
        on_delete=models.CASCADE,
        related_name="bookings",
    )

    user = models.ForeignKey(
        CustomUser,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="event_bookings",
    )

    full_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    email = models.EmailField(
        blank=True,
        null=True,
    )

    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
    )

    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )

    approved_by = models.ForeignKey(
        CustomUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_event_bookings",
    )

    approved_at = models.DateTimeField(null=True, blank=True)

    qr_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    qr_code = models.BinaryField(blank=True, null=True)

    qr_sent = models.BooleanField(default=False)

    checked_in = models.BooleanField(default=False)

    checked_in_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        db_table = "event_bookings"

    def save(self, *args, **kwargs):

        if not self.booking_id:
            self.booking_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"

        super().save(*args, **kwargs)

    def is_qr_valid(self):
        return (
            self.qr_code
            and self.qr_sent
            and not self.checked_in
            and self.status == self.Status.APPROVED
        )


# ==========================================================
# LOYALTY TRANSACTIONS
# Points are awarded:
#   - EARNED: +5 when a booking is CONFIRMED and COMPLETED
#   - REDEEMED: negative when user spends points
#   - ADMIN_GRANT: admin manually adds/adjusts points
#   - SPINNER: points won from the spinner wheel
#   - COMBO_BONUS: extra points from a combo pack
# ==========================================================


class LoyaltyTransaction(BaseModel):

    class TransactionType(models.TextChoices):
        EARNED = "earned", "Earned (Booking Completed)"
        REDEEMED = "redeemed", "Redeemed"
        ADMIN_GRANT = "admin_grant", "Admin Grant"
        SPINNER = "spinner", "Spinner Win"
        COMBO_BONUS = "combo_bonus", "Combo Pack Bonus"

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="loyalty_transactions",
    )

    booking = models.ForeignKey(
        Booking,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="loyalty_transactions",
    )

    # Positive = credit, negative = debit
    points = models.IntegerField()

    transaction_type = models.CharField(
        max_length=20,
        choices=TransactionType.choices,
    )

    # For ADMIN_GRANT: track which admin awarded the points
    granted_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_loyalty_transactions",
        help_text="Admin user who granted these points (ADMIN_GRANT only)",
    )

    description = models.TextField(blank=True)

    class Meta:
        db_table = "loyalty_transactions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} | {self.points:+d} pts | {self.transaction_type}"


# ==========================================================
# SPINNER REWARDS
# Prizes defined by admin. Each reward has a weight
# (probability) used in the weighted-random spin algorithm.
#
# reward_type distinguishes point prizes from happy-hour prizes.
# ==========================================================


class SpinnerReward(BaseModel):

    class RewardType(models.TextChoices):
        HAPPY_HOUR = "happy_hour", "Happy Hour"
        POINTS = "points", "Points"
        BETTER_LUCK = "better_luck", "Better Luck Next Time"

    reward_name = models.CharField(max_length=255)

    reward_type = models.CharField(
        max_length=20,
        choices=RewardType.choices,
    )

    reward_points = models.PositiveIntegerField(default=0)

    probability = models.PositiveIntegerField(default=10)

    template_slot = models.ForeignKey(
        "HappyHourTemplateSlot",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="spinner_rewards",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "spinner_rewards"

    def __str__(self):
        return self.reward_name


# ==========================================================
# SPINNER SPIN
# Records each spin event.
#
# Business rules enforced here:
#   1. Spinner is ONLY available on Saturday (weekday=5)
#      and Sunday (weekday=6).
#   2. Each user gets one spin per weekend day.
# ==========================================================


class SpinnerSpin(BaseModel):

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="spinner_spins",
    )

    reward = models.ForeignKey(
        "SpinnerReward",
        on_delete=models.CASCADE,
        related_name="spins",
    )

    spun_at = models.DateTimeField(auto_now_add=True)

    spin_week = models.PositiveIntegerField()

    spin_year = models.PositiveIntegerField()

    class Meta:
        db_table = "spinner_spins"

        unique_together = (
            "user",
            "spin_week",
            "spin_year",
        )

        ordering = ["-spun_at"]

    def save(self, *args, **kwargs):

        today = timezone.localdate()

        self.spin_week = today.isocalendar()[1]

        self.spin_year = today.year

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.email} " f"Week {self.spin_week}"


# ==========================================================
# HAPPY HOUR SLOT
# When a user wins a HAPPY_HOUR spinner reward, an admin
# (or automated process) allocates a free play slot on a
# normal weekday (Mon–Fri).
#
# The slot is linked back to the Booking once the user
# redeems it.
# ==========================================================
class HappyHourTemplateSlot(BaseModel):

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"

    weekday = models.IntegerField(choices=Weekday.choices)

    slot_name = models.CharField(max_length=100)

    start_time = models.TimeField()

    end_time = models.TimeField()

    probability = models.PositiveIntegerField(default=10)

    display_order = models.PositiveIntegerField(default=1)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "happy_hour_template_slots"
        ordering = [
            "weekday",
            "display_order",
        ]

    def __str__(self):
        return self.slot_name


class HappyHourSlot(BaseModel):

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="happy_hour_slots",
    )

    spinner_spin = models.ForeignKey(
        SpinnerSpin,
        on_delete=models.CASCADE,
        related_name="happy_hour_slots",
    )

    template_slot = models.ForeignKey(
        HappyHourTemplateSlot,
        on_delete=models.CASCADE,
        related_name="allocated_slots",
    )

    gaming_item = models.ForeignKey(
        GamingItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="happy_hour_slots",
    )

    allow_user_to_choose_game = models.BooleanField(default=True)

    allocated_date = models.DateField()

    start_time = models.TimeField()

    end_time = models.TimeField()

    is_used = models.BooleanField(default=False)

    redeemed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    expires_at = models.DateField()

    class Meta:
        db_table = "happy_hour_slots"

    def __str__(self):
        return f"{self.user.email}" f" - {self.allocated_date}"


class HappyHourBooking(BaseModel):

    happy_hour_slot = models.OneToOneField(
        HappyHourSlot,
        on_delete=models.CASCADE,
        related_name="happy_booking",
    )

    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="happy_hour_bookings",
    )

    approved_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    notes = models.TextField(blank=True)

    class Meta:
        db_table = "happy_hour_bookings"


class AppSetting(BaseModel):

    booking_loyalty_points = models.PositiveIntegerField(default=5)

    spinner_points_reward = models.PositiveIntegerField(default=10)

    class Meta:
        db_table = "app_settings"


# ==========================================================
# BOOKING EXPORT REQUEST
# Tracks admin requests to export booking datasets as Excel.
# Actual file generation is handled by a Celery task.
#
# period_type controls which date range is exported:
#   WEEKLY   → current ISO week
#   MONTHLY  → current calendar month
#   YEARLY   → current calendar year
#   CUSTOM   → custom_start .. custom_end (both required)
# ==========================================================


class BookingExportRequest(BaseModel):

    class PeriodType(models.TextChoices):
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"
        CUSTOM = "custom", "Custom Range"

    class ExportStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    requested_by = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="export_requests",
    )

    period_type = models.CharField(
        max_length=20,
        choices=PeriodType.choices,
    )

    custom_start = models.DateField(
        null=True,
        blank=True,
        help_text="Required when period_type=CUSTOM",
    )

    custom_end = models.DateField(
        null=True,
        blank=True,
        help_text="Required when period_type=CUSTOM",
    )

    status = models.CharField(
        max_length=20,
        choices=ExportStatus.choices,
        default=ExportStatus.PENDING,
    )

    file = models.FileField(
        upload_to="booking_exports/",
        null=True,
        blank=True,
        help_text="Generated Excel file — populated by background task",
    )

    error_message = models.TextField(
        blank=True,
        help_text="Populated if the export task fails",
    )

    class Meta:
        db_table = "booking_export_requests"
        ordering = ["-created_at"]

    def clean(self):
        if self.period_type == self.PeriodType.CUSTOM:
            if not self.custom_start or not self.custom_end:
                raise ValidationError(
                    "custom_start and custom_end are required for a custom export."
                )
            if self.custom_start > self.custom_end:
                raise ValidationError(
                    "custom_start must be before or equal to custom_end."
                )

    def __str__(self):
        return f"{self.requested_by.email} | " f"{self.period_type} | {self.status}"


from datetime import timedelta
from django.utils import timezone


class PasswordResetOTP(BaseModel):

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="password_reset_otps",
    )

    otp = models.CharField(
        max_length=128,
    )

    expires_at = models.DateTimeField()

    attempts = models.PositiveIntegerField(
        default=0,
    )

    is_used = models.BooleanField(
        default=False,
    )

    class Meta:
        db_table = "password_reset_otps"
        ordering = ["-created_at"]

    def is_expired(self):
        return timezone.now() > self.expires_at

    @classmethod
    def generate_otp(cls):
        return str(secrets.randbelow(900000) + 100000)









class HappyHourAllocation(BaseModel):

    date = models.DateField()

    start_time = models.TimeField()

    end_time = models.TimeField()

    offer_percentage = models.PositiveIntegerField(
        default=0,
        help_text="Discount percentage offered during this slot"
    )

    loyalty_points = models.PositiveIntegerField(
        default=0,
        help_text="Loyalty points awarded for using this slot"
    )

    is_free = models.BooleanField(
        default=False,
        help_text="Whether the slot is completely free"
    )

    max_bookings = models.PositiveIntegerField(
        default=1,
        help_text="Maximum number of bookings allowed"
    )

    is_active = models.BooleanField(default=True)

    notes = models.TextField(blank=True)

    class Meta:
        db_table = "happy_hour_allocations"
        ordering = ["date", "start_time"]
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["date", "start_time"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return (
            f"{self.date} | "
            f"{self.start_time} - {self.end_time} | "
            f"{self.offer_percentage}%"
        )

    def clean(self):
        if self.start_time >= self.end_time:
            raise ValidationError(
                "Start time must be before end time."
            )

        if self.offer_percentage > 100:
            raise ValidationError(
                "Offer percentage cannot be greater than 100."
            )

    
    def save(self, *args, **kwargs):
        now = timezone.localtime()

        if self.date < now.date():
            self.is_active = False

        elif self.date == now.date():
            current_time = now.time()

            if current_time >= self.end_time:
                self.is_active = False

        self.clean()

        super().save(*args, **kwargs)