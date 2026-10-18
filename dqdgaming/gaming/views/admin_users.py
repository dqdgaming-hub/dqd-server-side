"""Admin user-management views."""

import logging

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from gaming.models import CustomUser, UserDevice
from gaming.permissions import IsAdminUserRole
from gaming.serializers import (
    AdminUserDetailSerializer,
    AdminUserListSerializer,
    AdminUserWriteSerializer,
)
from gaming.utils import whatsapp
from gaming.views.common import paginate

logger = logging.getLogger(__name__)


def _parse_bool(value, default=None):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


class AdminUserListView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def get(self, request):

        search = (request.GET.get("search") or "").strip()[:100]

        queryset = CustomUser.objects.filter(role="user", is_deleted=False)

        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
            )

        return paginate(request, queryset.order_by("-created_at"), AdminUserListSerializer)

    @transaction.atomic
    def post(self, request):
        """Admin adds a customer (name, mobile, password) and gets a WhatsApp link."""
        serializer = AdminUserWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        password = serializer.validated_data["password"]

        logger.info("Admin %s created user %s", request.user.pk, user.pk)

        return Response(
            {
                "success": True,
                "user": AdminUserListSerializer(user, context={"request": request}).data,
                "whatsapp_url": whatsapp.generate_whatsapp_url(
                    user.phone,
                    whatsapp.account_credentials_message(user, password, is_new=True),
                ),
            },
            status=status.HTTP_201_CREATED,
        )


class AdminUserDetailView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def get(self, request, pk):

        user = get_object_or_404(
            CustomUser.objects.prefetch_related("devices"),
            pk=pk,
            is_deleted=False,
        )

        serializer = AdminUserDetailSerializer(
            user,
            context={"request": request},
        )

        return Response(serializer.data)

    @transaction.atomic
    def patch(self, request, pk):
        """Edit name / mobile / email / password / active flag."""
        user = get_object_or_404(
            CustomUser.objects.select_for_update(),
            pk=pk,
            role=CustomUser.Role.USER,
            is_deleted=False,
        )
        serializer = AdminUserWriteSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        password = serializer.validated_data.get("password") or ""

        whatsapp_url = None
        if password:
            whatsapp_url = whatsapp.generate_whatsapp_url(
                user.phone,
                whatsapp.account_credentials_message(user, password, is_new=False),
            )

        logger.info("Admin %s updated user %s", request.user.pk, user.pk)

        return Response(
            {
                "success": True,
                "user": AdminUserListSerializer(user, context={"request": request}).data,
                "whatsapp_url": whatsapp_url,
            }
        )


class AdminUserStatusView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def patch(self, request, pk):

        user = get_object_or_404(CustomUser, pk=pk, is_deleted=False)

        if user.pk == request.user.pk:
            return Response({"detail": "You cannot change your own status."}, status=400)

        is_active = _parse_bool(request.data.get("is_active"))
        if is_active is None:
            return Response({"detail": "is_active must be true or false."}, status=400)

        user.is_active = is_active
        update_fields = ["is_active", "updated_at"]
        if is_active:
            # Re-activating also clears a login lockout.
            user.failed_login_attempts = 0
            user.locked_until = None
            update_fields += ["failed_login_attempts", "locked_until"]
        user.save(update_fields=update_fields)

        if not is_active:
            UserDevice.objects.filter(user=user, is_online=True).update(
                is_online=False, logged_out_at=timezone.now()
            )

        return Response({"success": True, "is_active": user.is_active})


class AdminUserDeleteView(APIView):

    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def delete(self, request, pk):

        user = get_object_or_404(CustomUser, pk=pk, is_deleted=False)

        if user.pk == request.user.pk or user.role == CustomUser.Role.ADMIN:
            return Response({"detail": "Admin accounts cannot be deleted here."}, status=400)

        # Soft delete: keep bookings / accounting history intact and free the
        # mobile number + email for re-use.
        user.is_deleted = True
        user.is_active = False
        user.phone = None
        user.email = None
        user.save(update_fields=["is_deleted", "is_active", "phone", "email", "updated_at"])
        UserDevice.objects.filter(user=user, is_online=True).update(
            is_online=False, logged_out_at=timezone.now()
        )

        return Response(status=204)
