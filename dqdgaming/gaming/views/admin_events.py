"""Admin event-booking views (list, approve, reject, QR verification)."""

import uuid

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from gaming.models import EventBooking
from gaming.permissions import IsAdminUserRole
from gaming.serializers import (
    AdminEventBookingCreateSerializer,
    AdminEventBookingDetailSerializer,
    AdminEventBookingSerializer,
)
from gaming.utils import whatsapp
from gaming.utils.emailjs import send_emailjs
from gaming.utils.image_encryption import safe_image_to_data_uri
from gaming.utils.qr import generate_qr_code
from gaming.utils.tasks import run_in_background
from gaming.views.common import paginate, store_encrypted_qr_code


class AdminEventBookingListCreateView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    def get(self, request):

        queryset = EventBooking.objects.select_related(
            "event",
            "user",
        ).order_by("-created_at")

        status_filter = request.query_params.get("status")
        if status_filter in EventBooking.Status.values:
            queryset = queryset.filter(status=status_filter)

        search = (request.query_params.get("search") or "").strip()[:100]
        if search:
            queryset = queryset.filter(
                Q(booking_id__icontains=search)
                | Q(full_name__icontains=search)
                | Q(phone__icontains=search)
                | Q(event__title__icontains=search)
            )

        return paginate(request, queryset, AdminEventBookingSerializer)

    @transaction.atomic
    def post(self, request):

        serializer = AdminEventBookingCreateSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        booking = serializer.save()

        data = AdminEventBookingDetailSerializer(
            booking, context={"request": request}
        ).data
        data["whatsapp_url"] = whatsapp.event_booking_whatsapp_url(booking, added_by_admin=True)

        return Response(data, status=201)


class AdminEventBookingDetailView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    def get(self, request, pk):

        booking = get_object_or_404(
            EventBooking,
            pk=pk,
        )

        return Response(
            AdminEventBookingDetailSerializer(
                booking, context={"request": request}
            ).data
        )


class AdminEventBookingApproveView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    @transaction.atomic
    def post(self, request, pk):

        booking = get_object_or_404(
            EventBooking.objects.select_for_update(of=("self",)).select_related("event", "user"),
            pk=pk,
        )

        if booking.status == EventBooking.Status.APPROVED:
            return Response(
                {"detail": "Booking is already approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if booking.status in (EventBooking.Status.CANCELLED, EventBooking.Status.ATTENDED):
            return Response(
                {"detail": f"A {booking.status} booking cannot be approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── 1. Update booking status ──────────────────────────
        booking.status = EventBooking.Status.APPROVED
        booking.approved_by = request.user
        booking.approved_at = timezone.now()

        # ── 2. Generate QR code (once) ────────────────────────
        if not booking.qr_code:
            qr_file = generate_qr_code(
                data=str(booking.qr_token),
                filename=f"event_qr_{booking.booking_id}.png",
            )
            store_encrypted_qr_code(booking, qr_file)

        booking.save()

        # ── 3. Build decrypted QR data URI for email ────────────
        qr_url = safe_image_to_data_uri(booking.qr_code) or ""
        # ── 4. Resolve recipient email ────────────────────────
        recipient_email = booking.user.email if booking.user else booking.email
        recipient_name = (
            booking.user.full_name if booking.user else (booking.full_name or "Guest")
        )

        whatsapp_url = whatsapp.event_booking_whatsapp_url(booking)

        if not recipient_email:
            return Response(
                {
                    "success": True,
                    "booking_id": booking.booking_id,
                    "warning": "Approved. No email on file — send the WhatsApp message instead.",
                    "whatsapp_url": whatsapp_url,
                }
            )

        # ── 5. Send email via EmailJS ─────────────────────────
        event = booking.event

        template_params = {
            "to_email": recipient_email,
            "customer_name": recipient_name,
            "booking_id": booking.booking_id,
            "event_name": event.title,
            "event_date": event.event_date.strftime("%d %B %Y"),
            "event_location": getattr(event, "location", "DQD Gaming Arena"),
            "amount_paid": str(booking.amount_paid),
            "qr_code_url": qr_url,
        }

        run_in_background(_send_event_qr_email, booking.pk, template_params)

        return Response(
            {
                "success": True,
                "booking_id": booking.booking_id,
                "email": recipient_email,
                "qr_sent": booking.qr_sent,
                "mail_queued": True,
                "whatsapp_url": whatsapp_url,
            }
        )


def _send_event_qr_email(booking_pk, template_params):
    if send_emailjs(template_params):
        EventBooking.objects.filter(pk=booking_pk).update(qr_sent=True)


class AdminEventBookingRejectView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    @transaction.atomic
    def post(self, request, pk):

        booking = get_object_or_404(
            EventBooking.objects.select_for_update(of=("self",)).select_related("event", "user"),
            pk=pk,
        )

        if booking.status in (EventBooking.Status.ATTENDED, EventBooking.Status.CANCELLED):
            return Response(
                {"detail": f"A {booking.status} booking cannot be rejected."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        booking.status = EventBooking.Status.REJECTED

        booking.save(update_fields=["status", "updated_at"])

        return Response(
            {
                "success": True,
            }
        )


class AdminVerifyEventQRView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    @transaction.atomic
    def post(self, request):

        qr_token = (request.data.get("qr_token") or "").strip()

        if not qr_token:
            return Response(
                {"valid": False, "error": "QR token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            uuid.UUID(qr_token)
        except (ValueError, AttributeError, TypeError):
            return Response(
                {"valid": False, "error": "Invalid QR code format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        booking = (
            EventBooking.objects.select_for_update()
            .filter(qr_token=qr_token)
            .first()
        )
        if booking is None:
            return Response(
                {"valid": False, "error": "No booking found for this QR code."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Optional: stop a code from being "checked in" twice.
        # Drop this block if you want re-scans to just succeed again.
        if booking.checked_in:
            return Response(
                {
                    "valid": False,
                    "error": "This booking has already been checked in.",
                    "booking_id": booking.booking_id,
                    "name": booking.full_name,
                    "event": booking.event.title,
                },
                status=status.HTTP_409_CONFLICT,
            )

        if not booking.is_qr_valid():
            return Response(
                {
                    "valid": False,
                    "error": "This booking is not valid for check-in.",
                    "booking_id": booking.booking_id,
                    "name": booking.full_name,
                    "event": booking.event.title,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        booking.checked_in = True
        booking.checked_in_at = timezone.now()
        booking.status = EventBooking.Status.ATTENDED
        booking.save()

        return Response(
            {
                "valid": True,
                "booking_id": booking.booking_id,
                "name": booking.full_name,
                "event": booking.event.title,
            }
        )
