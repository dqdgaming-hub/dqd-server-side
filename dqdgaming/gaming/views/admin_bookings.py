"""Admin game/combo booking views (list, approve, reject, QR verification)."""

import uuid
from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from gaming.models import Booking
from gaming.permissions import IsAdminUserRole
from gaming.serializers import (
    AdminBookingCreateSerializer,
    AdminBookingDetailSerializer,
    AdminBookingListSerializer,
)
from gaming.utils import whatsapp
from gaming.utils.emailjs import send_game_booking_email
from gaming.utils.loyalty import (
    award_booking_loyalty_points,
    reverse_booking_loyalty_points,
)
from gaming.utils.qr import generate_qr_code
from gaming.utils.tasks import run_in_background
from gaming.views.common import paginate, store_encrypted_qr_code


def _ensure_booking_qr(booking):
    if not booking.qr_code:
        qr_file = generate_qr_code(
            data=str(booking.qr_token),
            filename=f"booking_{booking.booking_id}.png",
        )
        store_encrypted_qr_code(booking, qr_file)


def _send_booking_email(booking_pk):
    booking = (
        Booking.objects.select_related("user", "item", "combo_pack")
        .prefetch_related("members")
        .filter(pk=booking_pk)
        .first()
    )
    if booking and send_game_booking_email(booking, None) and booking.qr_code:
        Booking.objects.filter(pk=booking_pk).update(qr_sent=True)


class AdminBookingListCreateView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def get(self, request):
        queryset = (
            Booking.objects.select_related("user", "item", "combo_pack")
            .prefetch_related("members", "loyalty_transactions")
            .filter(is_deleted=False)
            .order_by("-created_at")
        )

        status_filter = request.query_params.get("status")
        if status_filter in Booking.Status.values:
            queryset = queryset.filter(status=status_filter)

        booking_type = request.query_params.get("type")
        if booking_type == "combo":
            queryset = queryset.filter(combo_pack__isnull=False)
        elif booking_type == "game":
            queryset = queryset.filter(combo_pack__isnull=True)

        booking_date = request.query_params.get("date")
        if booking_date:
            try:
                queryset = queryset.filter(
                    booking_date=datetime.strptime(booking_date, "%Y-%m-%d").date()
                )
            except ValueError:
                return Response({"detail": "date must use YYYY-MM-DD format."}, status=400)

        search = (request.query_params.get("search") or "").strip()[:100]
        if search:
            queryset = queryset.filter(
                Q(booking_id__icontains=search)
                | Q(guest_name__icontains=search)
                | Q(guest_phone__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(user__phone__icontains=search)
                | Q(item__name__icontains=search)
                | Q(combo_pack__name__icontains=search)
            )

        return paginate(request, queryset, AdminBookingListSerializer)

    @transaction.atomic
    def post(self, request):
        serializer = AdminBookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()

        if booking.status == Booking.Status.CONFIRMED:
            _ensure_booking_qr(booking)
            booking.approved_by = request.user
            booking.approved_at = timezone.now()
            booking.save(update_fields=["qr_code", "approved_by", "approved_at", "updated_at"])

        if booking.status != Booking.Status.CANCELLED:
            award_booking_loyalty_points(
                booking=booking,
                admin_user=request.user,
            )
        # Refresh so members / related objects are available
        booking.refresh_from_db()

        if booking.customer_email:
            run_in_background(_send_booking_email, booking.pk)

        data = AdminBookingDetailSerializer(booking, context={"request": request}).data
        data["whatsapp_url"] = whatsapp.booking_whatsapp_url(booking, added_by_admin=True)
        return Response(data, status=201)


class AdminBookingDetailView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def get(self, request, pk):
        booking = get_object_or_404(Booking, pk=pk)
        return Response(
            AdminBookingDetailSerializer(booking, context={"request": request}).data
        )

    @transaction.atomic
    def patch(self, request, pk):

        booking = get_object_or_404(
            Booking.objects.select_for_update(of=("self",)).select_related("user", "item", "combo_pack"),
            pk=pk,
        )

        old_status = booking.status
        old_payment_status = booking.payment_status

        new_status = request.data.get("status", booking.status)
        new_payment_status = request.data.get("payment_status", booking.payment_status)
        notes = request.data.get("notes", booking.notes)

        if new_status not in Booking.Status.values:
            return Response({"detail": "Invalid booking status."}, status=400)
        if new_payment_status not in Booking.PaymentStatus.values:
            return Response({"detail": "Invalid payment status."}, status=400)
        if not isinstance(notes, str) or len(notes) > 2000:
            return Response({"detail": "Notes must be text up to 2000 characters."}, status=400)
        if old_status == Booking.Status.CANCELLED and new_status != old_status:
            return Response({"detail": "A cancelled booking cannot be reopened. Create a new booking."}, status=400)

        booking.status = new_status
        booking.payment_status = new_payment_status
        booking.notes = notes

        # Add payment only once
        if (
            old_payment_status != Booking.PaymentStatus.PAID
            and booking.payment_status == Booking.PaymentStatus.PAID
        ):
            booking.price_paid = booking.total_amount or Decimal("0.00")

        if new_status == Booking.Status.CONFIRMED and old_status != new_status:
            _ensure_booking_qr(booking)
            booking.approved_by = request.user
            booking.approved_at = timezone.now()

        if new_status == Booking.Status.CANCELLED and old_status != new_status:
            booking.cancelled_at = timezone.now()
            booking.cancelled_by = request.user
            booking.cancelled_from = "admin"

        booking.save()

        if new_status in (Booking.Status.CONFIRMED, Booking.Status.COMPLETED):
            award_booking_loyalty_points(booking, admin_user=request.user)
        elif new_status == Booking.Status.CANCELLED and old_status != new_status:
            reverse_booking_loyalty_points(booking)

        data = AdminBookingDetailSerializer(booking, context={"request": request}).data
        data["whatsapp_url"] = (
            whatsapp.booking_whatsapp_url(booking)
            if new_status == Booking.Status.CONFIRMED and old_status != new_status
            else None
        )
        return Response(data)


class AdminBookingApproveView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    @transaction.atomic
    def post(self, request, pk):
        booking = get_object_or_404(
            Booking.objects.select_for_update(of=("self",)).select_related("user", "item", "combo_pack"),
            pk=pk,
        )

        if booking.status in (Booking.Status.CANCELLED, Booking.Status.COMPLETED):
            return Response(
                {"detail": f"A {booking.status} booking cannot be approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        booking.status = Booking.Status.CONFIRMED
        booking.approved_by = request.user
        booking.approved_at = timezone.now()

        _ensure_booking_qr(booking)

        booking.save()

        award_booking_loyalty_points(booking, admin_user=request.user)
        booking.refresh_from_db()

        if booking.customer_email:
            run_in_background(_send_booking_email, booking.pk)

        return Response(
            {
                "success": True,
                "mail_queued": bool(booking.customer_email),
                "booking_id": booking.booking_id,
                "whatsapp_url": whatsapp.booking_whatsapp_url(booking),
            }
        )


class AdminBookingRejectView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    @transaction.atomic
    def post(self, request, pk):

        booking = get_object_or_404(
            Booking.objects.select_for_update(of=("self",)).select_related("user", "item", "combo_pack"),
            pk=pk,
        )

        if booking.status == Booking.Status.CANCELLED:
            return Response({"detail": "Booking is already cancelled."}, status=400)
        if booking.status == Booking.Status.COMPLETED:
            return Response({"detail": "A completed booking cannot be cancelled."}, status=400)

        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.cancelled_by = request.user
        booking.cancelled_from = "admin"
        booking.cancellation_reason = str(request.data.get("reason") or "")[:500]
        if booking.payment_status == Booking.PaymentStatus.PAID and booking.price_paid:
            booking.refund_status = "pending"
            booking.refund_amount = booking.price_paid

        booking.save()
        reverse_booking_loyalty_points(booking)

        return Response({"success": True})


class AdminBookingVerifyQRView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    @transaction.atomic
    def post(self, request):

        qr_token = str(request.data.get("qr_token") or "").strip()

        try:
            uuid.UUID(qr_token)
        except (ValueError, AttributeError, TypeError):
            return Response(
                {"valid": False, "message": "Invalid QR", "detail": "Invalid QR code."},
                status=400,
            )

        booking = (
            Booking.objects.select_for_update(of=("self",))
            .select_related("user", "item", "combo_pack")
            .filter(qr_token=qr_token)
            .first()
        )

        if not booking:

            return Response(
                {
                    "valid": False,
                    "message": "Invalid QR",
                },
                status=400,
            )

        if booking.checked_in:

            return Response(
                {
                    "valid": False,
                    "message": "Already Checked In",
                },
                status=400,
            )

        if not booking.is_qr_valid:

            return Response(
                {
                    "valid": False,
                    "message": "QR Expired",
                },
                status=400,
            )

        booking.checked_in = True

        booking.checked_in_at = timezone.now()

        booking.save(update_fields=["checked_in", "checked_in_at", "updated_at"])

        return Response(
            {
                "valid": True,
                "booking_id": booking.booking_id,
                "customer": booking.customer_name,
                "item": (
                    booking.item.name
                    if booking.item
                    else booking.combo_pack.name
                    if booking.combo_pack
                    else ""
                ),
            }
        )


class AdminGameBookingListView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    def get(self, request):

        queryset = (
            Booking.objects.filter(combo_pack__isnull=True)
            .select_related(
                "user",
                "item",
            )
            .order_by("-created_at")
        )

        return Response(
            AdminBookingListSerializer(
                queryset,
                many=True,
            ).data
        )


class AdminComboBookingListView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    def get(self, request):

        queryset = (
            Booking.objects.filter(combo_pack__isnull=False)
            .select_related(
                "user",
                "combo_pack",
                "item",
            )
            .order_by("-created_at")
        )

        return Response(
            AdminBookingListSerializer(
                queryset,
                many=True,
            ).data
        )
