"""Admin loyalty-points views."""

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from gaming.models import CustomUser, LoyaltyTransaction
from gaming.permissions import IsAdminUserRole
from gaming.serializers import (
    AdminAdjustLoyaltySerializer,
    AdminUserLoyaltySerializer,
    LoyaltyTransactionSerializer,
)
from gaming.views.common import paginate


class AdminUserLoyaltyListView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    def get(self, request):

        users = (
            CustomUser.objects.filter(role="user", is_deleted=False)
            .annotate(
                total_transactions_count=Count("loyalty_transactions", distinct=True),
                redeemed_points_total=Sum(
                    "loyalty_transactions__points",
                    filter=Q(
                        loyalty_transactions__transaction_type=LoyaltyTransaction.TransactionType.REDEEMED
                    ),
                ),
            )
            .order_by("-created_at")
        )

        search = (request.query_params.get("search") or "").strip()[:100]
        if search:
            users = users.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(phone__icontains=search)
                | Q(email__icontains=search)
            )

        return paginate(request, users, AdminUserLoyaltySerializer)


class AdminUserLoyaltyHistoryView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    def get(self, request, pk):

        transactions = (
            LoyaltyTransaction.objects.filter(user_id=pk)
            .select_related(
                "granted_by",
                "booking",
            )
            .order_by("-created_at")
        )

        return Response(
            LoyaltyTransactionSerializer(
                transactions,
                many=True,
            ).data
        )


class AdminAdjustLoyaltyView(APIView):

    permission_classes = [
        IsAuthenticated,
        IsAdminUserRole,
    ]

    @transaction.atomic
    def post(self, request, pk):

        serializer = AdminAdjustLoyaltySerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        # Row lock: two admins adjusting at once cannot lose an update.
        user = get_object_or_404(
            CustomUser.objects.select_for_update(),
            pk=pk,
            is_deleted=False,
        )

        points = serializer.validated_data["points"]

        action = serializer.validated_data["action"]

        reason = serializer.validated_data["reason"]

        if action == "add":
            delta = points
            transaction_type = LoyaltyTransaction.TransactionType.ADMIN_GRANT
        else:
            if user.loyalty_points < points:
                return Response(
                    {
                        "detail": f"Insufficient points. Current balance is {user.loyalty_points}.",
                        "message": "Insufficient points.",
                    },
                    status=400,
                )
            delta = -points
            transaction_type = LoyaltyTransaction.TransactionType.REDEEMED

        user.loyalty_points += delta
        user.save(update_fields=["loyalty_points", "updated_at"])

        LoyaltyTransaction.objects.create(
            user=user,
            points=delta,
            transaction_type=transaction_type,
            granted_by=request.user,
            description=reason,
        )

        return Response(
            {
                "success": True,
                "current_points": user.loyalty_points,
            }
        )
