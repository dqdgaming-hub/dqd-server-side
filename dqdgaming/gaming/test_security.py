from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import unquote

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from gaming.models import (
    Booking,
    CustomUser,
    GameCategory,
    GamingItem,
    LoyaltyTransaction,
    PasswordResetOTP,
)
from gaming.utils.phone import InvalidPhone, normalize_phone
from gaming.utils.whatsapp import generate_whatsapp_url


PASSWORD = "Str0ng-Pass!9"

NO_THROTTLE = {
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {
        "anon": None, "user": None, "login": None, "register": None,
        "password_reset": None, "social_login": None, "public_home": None,
    },
}


def make_user(**extra):
    data = {"first_name": "Asha", "phone": "919876543210", "email": "asha@example.com"}
    data.update(extra)
    return CustomUser.objects.create_user(password=PASSWORD, **data)


def make_admin():
    return CustomUser.objects.create_superuser(
        email="admin@example.com", password=PASSWORD, first_name="Admin"
    )


@override_settings(DEFAULT_PHONE_COUNTRY_CODE="91", LOCAL_PHONE_LENGTH=10)
class PhoneAndWhatsAppTests(TestCase):
    def test_normalizes_local_and_international_numbers(self):
        self.assertEqual(normalize_phone("98765 43210"), "919876543210")
        self.assertEqual(normalize_phone("+91-98765-43210"), "919876543210")
        self.assertEqual(normalize_phone("0098765432101"), "98765432101")
        self.assertEqual(normalize_phone("09876543210"), "919876543210")
        self.assertIsNone(normalize_phone(""))
        with self.assertRaises(InvalidPhone):
            normalize_phone("abc")

    def test_whatsapp_url_matches_click_to_chat_format(self):
        url = generate_whatsapp_url("9876543210", "Hello! Here are the details.")
        self.assertTrue(url.startswith("https://wa.me/919876543210?text="))
        self.assertEqual(unquote(url.split("text=")[1]), "Hello! Here are the details.")
        self.assertIsNone(generate_whatsapp_url("", "hi"))


@override_settings(LOGIN_MAX_ATTEMPTS=3, LOGIN_LOCKOUT_MINUTES=15)
@patch.dict("rest_framework.settings.api_settings.__dict__", {"DEFAULT_THROTTLE_CLASSES": []})
class LoginLockoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = make_user()

    def login(self, identifier, password):
        return self.client.post(
            "/api/auth/login/", {"identifier": identifier, "password": password}, format="json"
        )

    def test_login_with_mobile_number_or_email(self):
        self.assertEqual(self.login("98765 43210", PASSWORD).status_code, 200)
        self.assertEqual(self.login("ASHA@example.com", PASSWORD).status_code, 200)

    def test_legacy_email_field_still_works(self):
        response = self.client.post(
            "/api/auth/login/", {"email": "asha@example.com", "password": PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200)

    def test_three_wrong_passwords_lock_the_account(self):
        first = self.login("9876543210", "wrong-1")
        self.assertEqual(first.status_code, 400)
        self.assertIn("2 attempts left", first.data["detail"])
        self.assertIn("1 attempt left", self.login("9876543210", "wrong-2").data["detail"])

        third = self.login("9876543210", "wrong-3")
        self.assertEqual(third.status_code, 429)
        self.assertTrue(third.data["locked"])

        # Even the right password is refused while locked.
        locked = self.login("9876543210", PASSWORD)
        self.assertEqual(locked.status_code, 429)

        self.user.refresh_from_db()
        self.assertGreater(self.user.locked_until, timezone.now())

    def test_lock_expires_and_success_resets_counter(self):
        self.login("9876543210", "wrong-1")
        self.assertEqual(self.login("9876543210", PASSWORD).status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 0)

        CustomUser.objects.filter(pk=self.user.pk).update(
            locked_until=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(self.login("9876543210", PASSWORD).status_code, 200)

    def test_unknown_account_gets_same_responses(self):
        self.assertIn("2 attempts left", self.login("9000000000", "x").data["detail"])
        self.login("9000000000", "x")
        self.assertEqual(self.login("9000000000", "x").status_code, 429)


@override_settings(PASSWORD_RESET_MAX_RESENDS=3, PASSWORD_RESET_RESEND_COOLDOWN_SECONDS=60)
@patch.dict("rest_framework.settings.api_settings.__dict__", {"DEFAULT_THROTTLE_CLASSES": []})
class OTPResendLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = make_user()

    def request_code(self):
        with patch("gaming.views.password.send_mail", return_value=1):
            return self.client.post(
                "/api/auth/forgot-password/", {"email": "asha@example.com"}, format="json"
            )

    def age_codes(self):
        PasswordResetOTP.objects.update(created_at=timezone.now() - timedelta(minutes=2))

    def test_first_code_plus_three_resends_then_blocked(self):
        expected_left = [3, 2, 1, 0]
        for left in expected_left:
            response = self.request_code()
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["resends_left"], left)
            self.age_codes()

        blocked = self.request_code()
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("maximum", blocked.data["detail"])
        self.assertEqual(PasswordResetOTP.objects.filter(user=self.user).count(), 4)
        self.assertEqual(
            PasswordResetOTP.objects.filter(user=self.user, is_used=False).count(), 1
        )

    def test_cooldown_between_resends(self):
        self.assertEqual(self.request_code().status_code, 200)
        too_soon = self.request_code()
        self.assertEqual(too_soon.status_code, 429)
        self.assertIn("wait", too_soon.data["detail"])


@patch.dict("rest_framework.settings.api_settings.__dict__", {"DEFAULT_THROTTLE_CLASSES": []})
class AdminUserManagementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.force_authenticate(make_admin())

    def test_admin_adds_user_with_mobile_and_gets_whatsapp_link(self):
        response = self.client.post(
            "/api/auth/admin/users/",
            {"first_name": "Ravi", "phone": "98765 11111", "password": "Gamer#2026x"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        user = CustomUser.objects.get(phone="919876511111")
        self.assertIsNone(user.email)
        self.assertTrue(user.check_password("Gamer#2026x"))
        self.assertTrue(response.data["whatsapp_url"].startswith("https://wa.me/919876511111?text="))
        self.assertIn("Gamer#2026x", unquote(response.data["whatsapp_url"]))

        # The new user can log in with the mobile number.
        login = APIClient().post(
            "/api/auth/login/", {"identifier": "9876511111", "password": "Gamer#2026x"}, format="json"
        )
        self.assertEqual(login.status_code, 200)

    def test_duplicate_mobile_and_weak_password_are_rejected(self):
        make_user()
        dup = self.client.post(
            "/api/auth/admin/users/",
            {"first_name": "X", "phone": "+91 98765 43210", "password": "Gamer#2026x"},
            format="json",
        )
        self.assertEqual(dup.status_code, 400)
        self.assertIn("phone", dup.data)

        weak = self.client.post(
            "/api/auth/admin/users/",
            {"first_name": "X", "phone": "9000000001", "password": "12345678"},
            format="json",
        )
        self.assertEqual(weak.status_code, 400)
        self.assertIn("password", weak.data)

    def test_admin_edits_user_and_password_change_unlocks(self):
        user = make_user()
        CustomUser.objects.filter(pk=user.pk).update(
            failed_login_attempts=2, locked_until=timezone.now() + timedelta(minutes=10)
        )
        response = self.client.patch(
            f"/api/auth/admin/users/{user.pk}/",
            {"first_name": "Asha K", "password": "N3w-Secret!x"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Asha K")
        self.assertIsNone(user.locked_until)
        self.assertTrue(user.check_password("N3w-Secret!x"))
        self.assertIn("wa.me", response.data["whatsapp_url"])

        no_password = self.client.patch(
            f"/api/auth/admin/users/{user.pk}/", {"last_name": "K"}, format="json"
        )
        self.assertIsNone(no_password.data["whatsapp_url"])

    def test_status_accepts_string_false(self):
        user = make_user()
        response = self.client.patch(
            f"/api/auth/admin/users/{user.pk}/status/", {"is_active": "false"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_delete_is_soft_and_keeps_bookings(self):
        user = make_user()
        response = self.client.delete(f"/api/auth/admin/users/{user.pk}/delete/")
        self.assertEqual(response.status_code, 204)
        user.refresh_from_db()
        self.assertTrue(user.is_deleted)
        self.assertIsNone(user.phone)

    def test_non_admin_is_forbidden(self):
        client = APIClient()
        client.force_authenticate(make_user())
        self.assertEqual(client.get("/api/auth/admin/users/").status_code, 403)


@patch.dict("rest_framework.settings.api_settings.__dict__", {"DEFAULT_THROTTLE_CLASSES": []})
class BookingLoyaltyTests(TestCase):
    def setUp(self):
        cache.clear()
        category = GameCategory.objects.create(name="PS5", category_type="ps5")
        self.item = GamingItem.objects.create(
            category=category, name="PS5 #1", price_per_hour=Decimal("200.00")
        )
        self.user = make_user()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def book(self, start=time(14, 0), end=time(15, 0)):
        return self.client.post(
            "/api/auth/user/bookings/create/",
            {
                "item": str(self.item.pk),
                "booking_date": str(date.today() + timedelta(days=2)),
                "start_time": start.strftime("%H:%M"),
                "end_time": end.strftime("%H:%M"),
            },
            format="json",
        )

    def test_points_are_not_credited_until_admin_confirms(self):
        response = self.book()
        self.assertEqual(response.status_code, 201, response.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.loyalty_points, 0)

        booking = Booking.objects.get(pk=response.data["booking"]["id"])
        admin = APIClient()
        admin.force_authenticate(make_admin())
        approve = admin.post(f"/api/auth/admin/bookings/{booking.pk}/approve/")
        self.assertEqual(approve.status_code, 200, approve.data)
        self.assertIn("wa.me", approve.data["whatsapp_url"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.loyalty_points, 10)

        # Approving twice never double-credits.
        admin.post(f"/api/auth/admin/bookings/{booking.pk}/approve/")
        self.user.refresh_from_db()
        self.assertEqual(self.user.loyalty_points, 10)

        # Admin cancel reverses the credit.
        cancel = admin.post(f"/api/auth/admin/bookings/{booking.pk}/reject/")
        self.assertEqual(cancel.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.loyalty_points, 0)

    def test_book_and_cancel_cannot_farm_points(self):
        for _ in range(3):
            booking_id = self.book().data["booking"]["id"]
            self.client.put(f"/api/auth/user/bookings/{booking_id}/cancel/")
        self.user.refresh_from_db()
        self.assertEqual(self.user.loyalty_points, 0)
        self.assertFalse(LoyaltyTransaction.objects.filter(user=self.user).exists())

    def test_overlapping_slot_is_rejected(self):
        self.assertEqual(self.book().status_code, 201)
        clash = self.book(time(14, 30), time(15, 30))
        self.assertEqual(clash.status_code, 400)
        self.assertIn("already booked", clash.data["detail"])

    def test_user_booking_returns_no_whatsapp_link(self):
        # WhatsApp goes admin → customer only (account, admin bookings, confirmations).
        response = self.book()
        self.assertNotIn("whatsapp_url", response.data)


class HealthCheckTests(TestCase):
    def test_health_ok(self):
        response = APIClient().get("/api/auth/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "ok")
        self.assertIn("X-Request-ID", response)


class ClientIPAndDeviceTests(TestCase):
    def meta_request(self, **meta):
        from types import SimpleNamespace
        return SimpleNamespace(META=meta)

    @override_settings(USE_X_FORWARDED_FOR=True, NUM_PROXIES_FOR_IP=1)
    def test_ip_uses_rightmost_proxy_entry_not_spoofed_left(self):
        from gaming.utills import get_client_ip
        request = self.meta_request(
            REMOTE_ADDR="10.0.0.2", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9"
        )
        self.assertEqual(get_client_ip(request), "203.0.113.9")

    @override_settings(USE_X_FORWARDED_FOR=False)
    def test_ip_ignores_forwarded_header_without_proxy(self):
        from gaming.utills import get_client_ip
        request = self.meta_request(REMOTE_ADDR="198.51.100.7", HTTP_X_FORWARDED_FOR="1.2.3.4")
        self.assertEqual(get_client_ip(request), "198.51.100.7")

    def test_client_hints_give_real_os_browser_and_model(self):
        import json
        from gaming.utills import get_device_info
        ua = (
            "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36"
        )
        hints = json.dumps({
            "platform": "Android", "platformVersion": "14.0.0", "model": "SM-S918B", "mobile": True,
            "brands": [{"brand": "Not=A?Brand", "version": "8"}, {"brand": "Chromium", "version": "129.0.6668.70"},
                       {"brand": "Google Chrome", "version": "129.0.6668.70"}],
            "screen": "412x915", "timezone": "Asia/Kolkata", "language": "en-IN",
        })
        info = get_device_info(self.meta_request(HTTP_USER_AGENT=ua, HTTP_X_CLIENT_INFO=hints))
        self.assertEqual(info["device_name"], "SM-S918B")
        self.assertEqual(info["operating_system"], "Android 14.0.0")
        self.assertEqual(info["browser"], "Google Chrome 129.0.6668.70")
        self.assertEqual(info["device_type"], "mobile")
        self.assertEqual(info["time_zone"], "Asia/Kolkata")

    def test_windows_11_detected_from_hints(self):
        import json
        from gaming.utills import get_device_info
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36"
        hints = json.dumps({"platform": "Windows", "platformVersion": "15.0.0"})
        info = get_device_info(self.meta_request(HTTP_USER_AGENT=ua, HTTP_X_CLIENT_INFO=hints))
        self.assertEqual(info["operating_system"], "Windows 11")
        self.assertEqual(info["device_type"], "desktop")

    def test_garbage_client_info_is_ignored(self):
        from gaming.utills import get_device_info
        info = get_device_info(self.meta_request(HTTP_USER_AGENT="curl/8", HTTP_X_CLIENT_INFO="{not json"))
        self.assertEqual(info["screen_resolution"], "")


@patch.dict("rest_framework.settings.api_settings.__dict__", {"DEFAULT_THROTTLE_CLASSES": []})
class LoginActivityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()

    def test_success_failure_and_device_are_saved(self):
        from gaming.models import LoginActivity, UserDevice
        client = APIClient(REMOTE_ADDR="198.51.100.20", HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0) Firefox/131.0")
        client.post("/api/auth/login/", {"identifier": "9876543210", "password": "nope"}, format="json")
        ok = client.post("/api/auth/login/", {"identifier": "9876543210", "password": PASSWORD}, format="json")
        self.assertEqual(ok.status_code, 200)

        events = list(LoginActivity.objects.filter(user=self.user).values_list("event", flat=True))
        self.assertIn("login_failed", events)
        self.assertIn("login_success", events)

        device = UserDevice.objects.get(user=self.user, device_id=ok.data["device_id"])
        self.assertEqual(device.ip_address, device.first_ip_address)
        self.assertIn("Firefox", device.browser)

        admin = APIClient()
        admin.force_authenticate(make_admin())
        detail = admin.get(f"/api/auth/admin/users/{self.user.pk}/")
        self.assertEqual(len(detail.data["recent_logins"]), 2)
        self.assertEqual(len(detail.data["devices"]), 1)


class StaleRefreshTokenTests(TestCase):
    def test_refresh_for_deleted_user_returns_401_not_500(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        user = make_user()
        refresh = str(RefreshToken.for_user(user))
        CustomUser.objects.filter(pk=user.pk).delete()
        response = APIClient().post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(response.status_code, 401)
