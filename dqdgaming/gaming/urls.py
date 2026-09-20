# urls.py
# ============================================================
# URL config for all auth endpoints.
# Include in your root urls.py as:
#
#   path("api/auth/", include("gaming.urls")),
#
# Full endpoint map
# ─────────────────────────────────────────────────────────────
#  POST   api/auth/register/                  RegisterView
#  POST   api/auth/login/                     LoginView
#  POST   api/auth/logout/                    LogoutView
#  GET    api/auth/profile/                   ProfileView
#  PATCH  api/auth/profile/                   ProfileView
#  POST   api/auth/password/change/           PasswordChangeView
#  POST   api/auth/password/reset/            PasswordResetRequestView
#  POST   api/auth/password/reset/confirm/    PasswordResetConfirmView
#  POST   api/auth/email/verify/              EmailVerifyView
#  POST   api/auth/email/resend/              EmailResendView
#  POST   api/auth/token/refresh/             TokenRefreshView   (simplejwt)
#  POST   api/auth/token/verify/              TokenVerifyView    (simplejwt)
#  POST   api/auth/social/google/             GoogleLoginView
#  POST   api/auth/social/facebook/           FacebookLoginView
# ============================================================

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from gaming.views import *
from rest_framework.routers import DefaultRouter


urlpatterns = [
    # ── Registration & login ──────────────────────────────────
    path("home/", PublicHomeAPIView.as_view(), name="public-home"),
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path(
        "forgot-password/",
        ForgotPasswordAPIView.as_view(),
    ),
    path(
        "verify-forgot-otp/",
        VerifyForgotOTPAPIView.as_view(),
    ),
    path(
        "reset-password/",
        ResetPasswordAPIView.as_view(),
    ),
    # ── Profile ───────────────────────────────────────────────
    path("profile/", ProfileView.as_view(), name="auth-profile"),
    # ── Password ──────────────────────────────────────────────
    path("password/change/", PasswordChangeView.as_view(), name="auth-password-change"),
    path(
        "password/reset/",
        PasswordResetRequestView.as_view(),
        name="auth-password-reset",
    ),
    path(
        "password/reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="auth-password-reset-confirm",
    ),
    # ── Email verification ────────────────────────────────────
    path("email/verify/", EmailVerifyView.as_view(), name="auth-email-verify"),
    path("email/resend/", EmailResendView.as_view(), name="auth-email-resend"),
    # ── JWT token management (simplejwt built-ins) ────────────
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("token/verify/", TokenVerifyView.as_view(), name="token-verify"),
    # ── Social auth ───────────────────────────────────────────
    path("social/google/", GoogleLoginView.as_view(), name="auth-social-google"),
    path("social/facebook/", FacebookLoginView.as_view(), name="auth-social-facebook"),
    path("navbar-profile/", NavbarProfileView.as_view(), name="navbar-profile"),
    path("user/dashboard/", UserDashboardAPIView.as_view(), name="user-dashboard"),
    path("user/spin/", UserSpinView.as_view()),
    path(
        "admin/dashboard/",
        AdminDashboardAPIView.as_view(),
        name="admin-dashboard",
    ),
    path("devices/", MyDevicesView.as_view(), name="my-devices"),
    path("admin/categories/", AdminCategoryListCreateView.as_view()),
    path("admin/categories/<uuid:pk>/", AdminCategoryDetailView.as_view()),
    path("admin/games/", AdminGameListCreateView.as_view()),
    path("admin/games/<uuid:pk>/", AdminGameDetailView.as_view()),
    path("admin/combo-packs/", AdminComboPackListCreateView.as_view()),
    path("admin/combo-packs/<uuid:pk>/", AdminComboPackDetailView.as_view()),
    path("admin/events/", AdminEventListCreateView.as_view()),
    path("admin/events/<uuid:pk>/", AdminEventDetailView.as_view()),
    path("admin/users/", AdminUserListView.as_view()),
    path("admin/users/<uuid:pk>/", AdminUserDetailView.as_view()),
    path("admin/users/<uuid:pk>/status/", AdminUserStatusView.as_view()),
    path("admin/users/<uuid:pk>/delete/", AdminUserDeleteView.as_view()),
    path("admin/event-bookings/", AdminEventBookingListCreateView.as_view()),
    path("admin/event-bookings/<uuid:pk>/", AdminEventBookingDetailView.as_view()),
    path(
        "admin/event-bookings/<uuid:pk>/approve/",
        AdminEventBookingApproveView.as_view(),
    ),
    path(
        "admin/event-bookings/<uuid:pk>/reject/", AdminEventBookingRejectView.as_view()
    ),
    path("admin/event-bookings/verify-qr/", AdminVerifyEventQRView.as_view()),
    path(
        "admin/game-bookings/",
        AdminBookingListCreateView.as_view(),
    ),
    path(
        "admin/bookings/<uuid:pk>/",
        AdminBookingDetailView.as_view(),
    ),
    path(
        "admin/bookings/<uuid:pk>/approve/",
        AdminBookingApproveView.as_view(),
    ),
    path(
        "admin/bookings/<uuid:pk>/reject/",
        AdminBookingRejectView.as_view(),
    ),
    path(
        "admin/bookings/verify-qr/",
        AdminBookingVerifyQRView.as_view(),
    ),
    path(
        "admin/bookings/game-items/",
        AdminGameBookingListView.as_view(),
    ),
    path(
        "admin/bookings/combo-packs/",
        AdminComboBookingListView.as_view(),
    ),
    path(
        "admin/happy-hour-slots/",
        AdminHappyHourTemplateListCreateView.as_view(),
    ),
    path(
        "admin/spinner-rewards/",
        AdminSpinnerRewardListCreateView.as_view(),
    ),
    path(
        "admin/happy-hour-bookings/",
        AdminHappyHourBookingsView.as_view(),
    ),
    path(
        "admin/spinner-spins/",
        AdminSpinnerSpinsView.as_view(),
    ),
    path(
        "admin/happy-hour-slot/<uuid:pk>/assign-game/",
        AdminAssignHappyHourGameView.as_view(),
    ),
    path(
        "admin/verify-happy-hour/",
        AdminVerifyHappyHourView.as_view(),
    ),
    path(
        "admin/happy-hour-slots/<uuid:pk>/assign-game/",
        AdminAssignHappyHourGameView.as_view(),
    ),
    path(
        "admin/loyalty/users/",
        AdminUserLoyaltyListView.as_view(),
    ),
    path(
        "admin/loyalty/users/<uuid:pk>/history/",
        AdminUserLoyaltyHistoryView.as_view(),
    ),
    path(
        "admin/loyalty/users/<uuid:pk>/adjust/",
        AdminAdjustLoyaltyView.as_view(),
    ),
    # ==========================================================
    # ACCOUNTING
    # ==========================================================
    path(
        "admin/accounting/dashboard/",
        AdminAccountingDashboardAPIView.as_view(),
        name="admin-accounting-dashboard",
    ),
    path(
        "admin/accounting/revenue-chart/",
        AdminRevenueChartAPIView.as_view(),
        name="admin-revenue-chart",
    ),
    path(
        "admin/accounting/bookings/",
        AdminAccountingBookingsAPIView.as_view(),
        name="admin-accounting-bookings",
    ),
    path(
        "admin/accounting/profit-loss/",
        AdminProfitLossAPIView.as_view(),
        name="admin-profit-loss",
    ),
    path(
        "admin/accounting/export/pdf/",
        AdminAccountingPDFExportAPIView.as_view(),
        name="admin-accounting-export-pdf",
    ),
    path(
        "admin/accounting/export/excel/",
        AdminAccountingExcelExportAPIView.as_view(),
        name="admin-accounting-export-excel",
    ),
    path(
        "admin/accounting/google-sheet/",
        AdminAccountingGoogleSheetSyncAPIView.as_view(),
        name="admin-accounting-google-sheet",
    ),
    # ── Profile ───────────────────────────────────────────────
    path(
        "profile/",
        ProfileAPIView.as_view(),
        name="auth-profile",
    ),
    path(
        "profile/change-password/",
        ChangePasswordAPIView.as_view(),
        name="auth-change-password",
    ),
    # ---------------------------------User--------------------------------
    # ----------------------------
    # Games
    # ----------------------------
    path(
        "user/game-categories/",
        UserGameCategoryAPIView.as_view(),
        name="user-game-categories",
    ),
    path(
        "user/games/",
        UserGameListAPIView.as_view(),
        name="user-games",
    ),
    path(
        "user/games/<uuid:pk>/",
        UserGameDetailAPIView.as_view(),
        name="user-game-detail",
    ),
    # ----------------------------
    # Booking
    # ----------------------------
    path(
        "user/bookings/create/",
        UserBookingCreateAPIView.as_view(),
        name="user-booking-create",
    ),
    path(
        "user/bookings/",
        UserBookingListAPIView.as_view(),
        name="user-bookings",
    ),
    path(
        "user/bookings/history/",
        UserBookingHistoryAPIView.as_view(),
        name="user-booking-history",
    ),
    path(
        "user/bookings/<uuid:pk>/",
        UserBookingDetailAPIView.as_view(),
        name="user-booking-detail",
    ),
    path(
        "user/bookings/<uuid:pk>/cancel/",
        UserCancelBookingAPIView.as_view(),
        name="user-booking-cancel",
    ),
    path(
        "user/games/<uuid:pk>/available-slots/",
        UserAvailableSlotsAPIView.as_view(),
        name="user-available-slots",
    ),
    path(
        "user/ticket-bookings/", UserBookingWalletView.as_view(), name="user-bookings"
    ),
    path(
        "user/ticket-bookings/<str:booking_id>/cancel/",
        UserCancelBookingView.as_view(),
        name="user-cancel-booking",
    ),


    path(
            "user/loyalty/redeem-slot/",
            RedeemLoyaltySlotAPIView.as_view(),
            name="redeem-loyalty-slot",
        ),

    path("user/gaming-items/", UserGamingItemListAPIView.as_view(), name="user-gaming-items"),


    path(
    "user/gaming-items/<uuid:item_id>/available-slots/",
    AvailableGamingSlotsAPIView.as_view(),
    name="available-gaming-slots",
    ),

    path(
        "user/loyalty-points/",
        UserLoyaltyAPIView.as_view(),
        name="user-loyalty-points",
    ),




    path(
        "user/events/",
        UserUpcomingEventsAPIView.as_view(),
        name="user-events",
    ),

    path(
        "user/events/<uuid:pk>/book/",
        UserBookEventAPIView.as_view(),
        name="book-event",
    ),

    path(
        "user/event-bookings/",
        UserEventBookingsAPIView.as_view(),
        name="event-bookings",
    ),

    path(
        "user/event-bookings/upcoming/",
        UserUpcomingBookingsAPIView.as_view(),
        name="upcoming-event-bookings",
    ),

    path(
        "user/event-bookings/previous/",
        UserPreviousBookingsAPIView.as_view(),
        name="previous-event-bookings",
    ),

    path(
        "user/event-bookings/<uuid:pk>/cancel/",
        UserCancelEventBookingAPIView.as_view(),
        name="cancel-event-booking",
    ),








    
    path("user/combo-packs/", UserComboPackListAPIView.as_view(), name="user-combo-packs"),
    path("user/combo-packs/<uuid:id>/", UserComboPackDetailAPIView.as_view(), name="user-combo-pack-detail"),
    path("user/combo-packs/book/", CreateComboBookingAPIView.as_view(), name="user-book-combo"),
    path("user/combo-bookings/", UserComboBookingsAPIView.as_view(), name="user-combo-bookings"),
    path("user/combo-bookings/upcoming/", UpcomingComboBookingsAPIView.as_view(), name="user-upcoming-combo-bookings"),
    path("user/combo-bookings/previous/", PreviousComboBookingsAPIView.as_view(), name="user-previous-combo-bookings"),
    path("user/combo-bookings/<uuid:id>/cancel/", CancelComboBookingAPIView.as_view(), name="user-cancel-combo-booking"),


    path("terms/", TermsAPIView.as_view(), name="terms"),

    
    path("user/happy-hour/", UserHappyHourAPIView.as_view(), name="user-happy-hour",),



]



router = DefaultRouter()

router.register(
    r"admin/happy-hour-allocations",
    AdminHappyHourAllocationViewSet,
    basename="admin-happy-hour-allocation"
)

urlpatterns += router.urls     