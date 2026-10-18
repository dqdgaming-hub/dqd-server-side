"""Admin dashboard view."""

from django.db.models import Exists, F, OuterRef, Q, Sum
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from gaming.middleware import DeviceActivityMixin
from gaming.models import Booking, CustomUser, ExclusiveEvent, GamingItem, UserDevice
from gaming.permissions import IsAdminUserRole
from gaming.serializers import (
    AdminDashboardBookingSerializer,
    AdminDashboardDeviceSerializer,
    AdminDashboardGamingItemSerializer,
    AdminDashboardUserSerializer,
)


class AdminDashboardAPIView(DeviceActivityMixin, APIView):
    permission_classes = [
        permissions.IsAuthenticated,
        IsAdminUserRole,
    ]

    def get(self, request):
        today = timezone.localdate()

        users = CustomUser.objects.filter(
            is_deleted=False,
            role=CustomUser.Role.USER,
        )

        bookings = Booking.objects.filter(
            is_deleted=False,
        )

        gaming_items = GamingItem.objects.filter(
            is_deleted=False,
        )

        total_revenue = (
            bookings.filter(
                payment_status=Booking.PaymentStatus.PAID,
            )
            .aggregate(total=Sum("total_amount"))
            .get("total")
            or 0
        )

        recent_bookings = bookings.select_related("user", "item").order_by(
            "-created_at"
        )[:5]

        recent_users = users.annotate(
            is_online_flag=Exists(
                UserDevice.objects.filter(
                    user=OuterRef("pk"),
                    is_deleted=False,
                    is_online=True,
                )
            )
        ).order_by("-created_at")[:5]

        attention_items = (
            gaming_items.filter(Q(maintenance_mode=True) | Q(is_active=False))
            .select_related("category")
            .order_by("-updated_at")[:10]
        )
        devices = (
            UserDevice.objects.filter(is_deleted=False)
            .select_related("user")
            .annotate(is_online_flag=F("is_online"))
            .order_by("-last_seen")[:20]
        )

        data = {
            "stats": {
                "total_users": users.count(),
                "total_bookings": bookings.count(),
                "total_revenue": total_revenue,
                "active_games": gaming_items.filter(
                    is_active=True,
                    maintenance_mode=False,
                ).count(),
                "pending_bookings": bookings.filter(
                    status=Booking.Status.PENDING,
                ).count(),
                "upcoming_events": ExclusiveEvent.objects.filter(
                    is_deleted=False,
                    is_active=True,
                    event_date__gte=today,
                ).count(),
            },
            "recent_bookings": AdminDashboardBookingSerializer(
                recent_bookings,
                many=True,
                context={"request": request},
            ).data,
            "recent_users": AdminDashboardUserSerializer(
                recent_users,
                many=True,
                context={"request": request},
            ).data,
            "low_stock_or_maintenance": AdminDashboardGamingItemSerializer(
                attention_items,
                many=True,
                context={"request": request},
            ).data,
            "recent_devices": AdminDashboardDeviceSerializer(
                devices,
                many=True,
            ).data,
        }

        return Response(
            data,
            status=status.HTTP_200_OK,
        )
