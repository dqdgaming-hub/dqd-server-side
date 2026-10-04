from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from datetime import date, time

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import SimpleTestCase, override_settings
from django.contrib.auth.hashers import check_password, make_password
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.exceptions import ValidationError as DRFValidationError

from gaming.models import Booking, ComboPack, EventBooking, GamingItem
from gaming.serializers import AdminBookingCreateSerializer, BookingMemberSerializer
from gaming.utils.emailjs import send_game_booking_email
from gaming.utils.loyalty import award_booking_loyalty_points
from gaming.utills import get_client_ip
from gaming.views import (
	AdminCategoryDetailView,
	AdminCategoryListCreateView,
	AdminComboPackDetailView,
	AdminComboPackListCreateView,
	AdminEventDetailView,
	AdminEventListCreateView,
	AdminGameDetailView,
	AdminGameListCreateView,
	AvailableGamingSlotsAPIView,
	GoogleCodeLoginView,
	ForgotPasswordAPIView,
	PublicHomeAPIView,
	UserAvailableSlotsAPIView,
	_validate_password_reset_otp,
)


class BookingLoyaltyTests(SimpleTestCase):
	@patch("gaming.utils.loyalty.Booking.objects")
	def test_locks_only_booking_when_loading_nullable_relations(self, booking_manager):
		booking_manager.select_related.return_value.select_for_update.return_value.get.return_value = SimpleNamespace(
			user=None,
		)

		result = award_booking_loyalty_points.__wrapped__(SimpleNamespace(pk=1))

		self.assertIsNone(result)
		booking_manager.select_related.return_value.select_for_update.assert_called_once_with(
			of=("self",),
		)


class ClientIpTrackingTests(SimpleTestCase):
	@override_settings(USE_X_FORWARDED_FOR=True)
	def test_uses_first_forwarded_ip_when_proxy_header_is_trusted(self):
		request = SimpleNamespace(
			META={
				"REMOTE_ADDR": "10.0.0.5",
				"HTTP_X_FORWARDED_FOR": "198.51.100.24, 10.0.0.4",
			}
		)

		self.assertEqual(get_client_ip(request), "198.51.100.24")

	@override_settings(USE_X_FORWARDED_FOR=False)
	def test_ignores_forwarded_header_when_not_configured_to_trust_proxy(self):
		request = SimpleNamespace(
			META={
				"REMOTE_ADDR": "10.0.0.5",
				"HTTP_X_FORWARDED_FOR": "198.51.100.24",
			}
		)

		self.assertEqual(get_client_ip(request), "10.0.0.5")

	@override_settings(USE_X_FORWARDED_FOR=True)
	def test_rejects_invalid_forwarded_ip(self):
		request = SimpleNamespace(
			META={
				"REMOTE_ADDR": "10.0.0.5",
				"HTTP_X_FORWARDED_FOR": "not-an-ip",
			}
		)

		self.assertIsNone(get_client_ip(request))


class AdminBookingCreateSerializerTests(SimpleTestCase):
	def test_rejects_an_active_overlapping_booking_as_validation_error(self):
		item = SimpleNamespace()
		overlapping = MagicMock()
		overlapping.exists.return_value = True

		with patch("gaming.serializers.Booking.objects.filter", return_value=overlapping) as filter_bookings:
			with self.assertRaises(DRFValidationError) as raised:
				AdminBookingCreateSerializer().validate(
					{
						"user": SimpleNamespace(),
						"guest_name": "",
						"guest_email": "",
						"guest_phone": "",
						"item": item,
						"booking_date": "2026-10-05",
						"start_time": "10:00",
						"end_time": "11:00",
					}
				)

		self.assertEqual(
			str(raised.exception.detail["start_time"]),
			"This slot is already booked.",
		)
		self.assertEqual(
			filter_bookings.call_args.kwargs["status__in"],
			[Booking.Status.PENDING, Booking.Status.CONFIRMED],
		)

	@patch(
		"gaming.serializers.Booking.objects.create",
		side_effect=DjangoValidationError("This slot is already booked."),
	)
	def test_converts_model_validation_race_to_serializer_error(self, create_booking):
		with self.assertRaises(DRFValidationError) as raised:
			AdminBookingCreateSerializer().create(
				{
					"user": SimpleNamespace(),
					"item": SimpleNamespace(),
					"booking_date": "2026-10-05",
					"start_time": "10:00",
					"end_time": "11:00",
					"combo_pack": None,
				}
			)

		self.assertEqual(
			raised.exception.detail[0],
			"This slot is already booked.",
		)
		create_booking.assert_called_once()


class BookingModelValidationTests(SimpleTestCase):
	@patch("gaming.models.Booking.objects.filter")
	def test_combo_booking_does_not_conflict_with_unassigned_game_slot(
		self,
		filter_bookings,
	):
		booking = Booking(
			combo_pack=ComboPack(pk=1),
			booking_date=date(2026, 10, 5),
			start_time=time(10, 0),
			end_time=time(11, 0),
			guest_name="Guest",
			guest_email="guest@example.com",
			guest_phone="1234567890",
		)

		booking.clean()

		filter_bookings.assert_not_called()

	@patch("gaming.models.Booking.objects.filter")
	def test_only_active_bookings_block_a_game_slot(self, filter_bookings):
		overlapping = MagicMock()
		overlapping.exclude.return_value.exists.return_value = False
		filter_bookings.return_value = overlapping
		booking = Booking(
			item=GamingItem(pk=1),
			booking_date=date(2026, 10, 5),
			start_time=time(10, 0),
			end_time=time(11, 0),
			guest_name="Guest",
			guest_email="guest@example.com",
			guest_phone="1234567890",
		)

		booking.clean()

		self.assertEqual(
			filter_bookings.call_args.kwargs["status__in"],
			[Booking.Status.PENDING, Booking.Status.CONFIRMED],
		)


class GameBookingEmailTests(SimpleTestCase):
	@patch("gaming.utils.emailjs.send_emailjs", return_value=True)
	@patch(
		"gaming.utils.emailjs.safe_image_to_data_uri",
		return_value="data:image/png;base64,encoded-qr",
	)
	def test_email_uses_data_uri_for_encrypted_qr_bytes(
		self,
		safe_image_to_data_uri,
		send_emailjs,
	):
		members = MagicMock()
		members.all.return_value = []
		members.count.return_value = 0
		booking = SimpleNamespace(
			members=members,
			qr_code=b"encrypted-qr",
			customer_name="Customer",
			booking_id="booking-id",
			item=None,
			combo_pack=None,
			booking_date="2026-10-04",
			start_time="10:00",
			end_time="11:00",
			total_hours=1,
			is_happy_hour=False,
			subtotal=100,
			discount_amount=0,
			total_amount=100,
			price_paid=100,
			payment_status="paid",
			awarded_loyalty_points=10,
			qr_token="qr-token",
			customer_email="customer@example.com",
		)

		result = send_game_booking_email(booking, request=MagicMock())

		self.assertTrue(result)
		safe_image_to_data_uri.assert_called_once_with(b"encrypted-qr")
		template_params = send_emailjs.call_args.args[0]
		self.assertEqual(
			template_params["qr_code_url"],
			"data:image/png;base64,encoded-qr",
		)


class GoogleCodeLoginViewTests(SimpleTestCase):
	def setUp(self):
		self.factory = APIRequestFactory()
		self.payload = {
			"code": "authorization-code",
			"redirect_uri": "https://dqdgaming.com/sign-in",
		}

	@override_settings(
		GOOGLE_CLIENT_SECRET="",
		CORS_ALLOWED_ORIGINS=["https://dqdgaming.com"],
	)
	def test_requires_server_side_google_client_secret(self):
		request = self.factory.post(
			"/api/auth/social/google/code/",
			self.payload,
			format="json",
		)

		response = GoogleCodeLoginView.as_view()(request)

		self.assertEqual(response.status_code, 503)

	@override_settings(
		GOOGLE_CLIENT_SECRET="test-secret",
		CORS_ALLOWED_ORIGINS=["https://dqdgaming.com"],
	)
	def test_rejects_unapproved_redirect_uri(self):
		from unittest.mock import patch

		self.payload["redirect_uri"] = "https://attacker.example/sign-in"
		request = self.factory.post(
			"/api/auth/social/google/code/",
			self.payload,
			format="json",
		)

		with patch("gaming.views.http_requests.post") as google_token_exchange:
			response = GoogleCodeLoginView.as_view()(request)

		self.assertEqual(response.status_code, 400)
		google_token_exchange.assert_not_called()


class ProductionRegressionTests(SimpleTestCase):
	def setUp(self):
		self.factory = APIRequestFactory()
		self.regular_user = SimpleNamespace(
			pk="regular-user",
			is_authenticated=True,
			is_superuser=False,
			is_staff=False,
			role="user",
		)

	def test_catalog_admin_endpoints_reject_regular_users(self):
		endpoints = (
			(AdminCategoryListCreateView, "get"),
			(AdminCategoryDetailView, "put"),
			(AdminGameListCreateView, "get"),
			(AdminGameDetailView, "put"),
			(AdminComboPackListCreateView, "get"),
			(AdminComboPackDetailView, "put"),
			(AdminEventListCreateView, "get"),
			(AdminEventDetailView, "put"),
		)

		for view_class, method in endpoints:
			with self.subTest(view=view_class.__name__):
				request = getattr(self.factory, method)("/", {}, format="json")
				force_authenticate(request, user=self.regular_user)

				response = view_class.as_view()(request, pk="00000000-0000-0000-0000-000000000001")

				self.assertEqual(response.status_code, 403)

	def test_public_home_returns_success_with_empty_catalog(self):
		events = MagicMock()
		events.filter.return_value.order_by.return_value.__getitem__.return_value = []
		event_stats = MagicMock()
		event_stats.count.return_value = 0

		combos = MagicMock()
		combos.prefetch_related.return_value.__getitem__.return_value = []
		combo_stats = MagicMock()
		combo_stats.count.return_value = 0

		categories = MagicMock()
		categories.prefetch_related.return_value.order_by.return_value = []

		games = MagicMock()
		games.__getitem__.return_value = []
		game_stats = MagicMock()
		game_stats.count.return_value = 0

		users = MagicMock()
		users.count.return_value = 0

		with (
			patch("gaming.views.ExclusiveEvent.objects.filter", side_effect=[events, event_stats]),
			patch("gaming.views.ComboPack.objects.filter", side_effect=[combos, combo_stats]),
			patch("gaming.views.GameCategory.objects.filter", return_value=categories),
			patch("gaming.views.GamingItem.objects.filter", side_effect=[games, game_stats]),
			patch("gaming.views.CustomUser.objects.filter", return_value=users),
			patch("gaming.views.HomeSerializer") as home_serializer,
		):
			home_serializer.return_value.data = {}
			response = PublicHomeAPIView().get(self.factory.get("/"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data, {"success": True, "data": {}})

	def test_available_slots_rejects_malformed_date(self):
		request = self.factory.get("/", {"date": "not-a-date"})
		force_authenticate(request, user=self.regular_user)

		response = UserAvailableSlotsAPIView.as_view()(
			request,
			pk="00000000-0000-0000-0000-000000000001",
		)

		self.assertEqual(response.status_code, 400)

	def test_gaming_item_slots_reject_malformed_date(self):
		request = self.factory.get("/", {"date": "not-a-date"})
		force_authenticate(request, user=self.regular_user)

		response = AvailableGamingSlotsAPIView.as_view()(
			request,
			item_id="00000000-0000-0000-0000-000000000001",
		)

		self.assertEqual(response.status_code, 400)

	def test_event_qr_is_valid_only_for_approved_booking(self):
		booking = EventBooking(
			qr_code=b"encrypted-qr",
			qr_sent=True,
			status=EventBooking.Status.APPROVED,
		)

		self.assertTrue(booking.is_qr_valid())

		booking.status = EventBooking.Status.PENDING
		self.assertFalse(booking.is_qr_valid())

	def test_booking_member_cannot_claim_admin_added_flag(self):
		self.assertIn(
			"is_admin_added",
			BookingMemberSerializer.Meta.read_only_fields,
		)

	@patch("gaming.views.PasswordResetOTP.objects.select_for_update")
	def test_legacy_reset_code_is_verified_and_upgraded(self, select_for_update):
		record = SimpleNamespace(
			otp="123456",
			attempts=0,
			is_used=False,
			is_expired=lambda: False,
			save=MagicMock(),
		)
		select_for_update.return_value.filter.return_value.order_by.return_value.first.return_value = record

		result = _validate_password_reset_otp(
			SimpleNamespace(pk="user-id"),
			"123456",
		)

		self.assertIs(result, record)
		self.assertEqual(record.attempts, 1)
		self.assertTrue(check_password("123456", record.otp))

	@patch("gaming.views.PasswordResetOTP.objects.select_for_update")
	def test_reset_code_is_invalidated_after_five_failed_attempts(
		self,
		select_for_update,
	):
		record = SimpleNamespace(
			otp=make_password("123456"),
			attempts=4,
			is_used=False,
			is_expired=lambda: False,
			save=MagicMock(),
		)
		select_for_update.return_value.filter.return_value.order_by.return_value.first.return_value = record

		result = _validate_password_reset_otp(
			SimpleNamespace(pk="user-id"),
			"654321",
		)

		self.assertIsNone(result)
		self.assertEqual(record.attempts, 5)
		self.assertTrue(record.is_used)

	@patch("gaming.views.CustomUser.objects.select_for_update")
	def test_forgot_password_response_does_not_disclose_code_for_unknown_email(
		self,
		select_for_update,
	):
		select_for_update.return_value.filter.return_value.first.return_value = None
		view = ForgotPasswordAPIView()
		request = view.initialize_request(
			self.factory.post("/", {"email": "missing@example.com"}, format="json")
		)

		response = ForgotPasswordAPIView.post.__wrapped__(view, request)

		self.assertEqual(response.status_code, 200)
		response_data = response.data if isinstance(response.data, dict) else {}
		self.assertNotIn("otp", response_data)
		self.assertIn(
			"If an account with that email exists",
			response_data.get("message", ""),
		)

	@patch("gaming.views.send_mail", return_value=1)
	@patch("gaming.views.PasswordResetOTP.objects.create")
	@patch("gaming.views.PasswordResetOTP.objects.filter")
	@patch("gaming.views.CustomUser.objects.select_for_update")
	@patch("gaming.views.PasswordResetOTP.generate_otp", return_value="123456")
	def test_forgot_password_sends_code_and_stores_only_hash(
		self,
		_generate_otp,
		select_for_update,
		otp_filter,
		create_otp,
		send_mail_mock,
	):
		user = SimpleNamespace(email="user@example.com")
		select_for_update.return_value.filter.return_value.first.return_value = user
		create_otp.return_value = MagicMock()
		view = ForgotPasswordAPIView()
		request = view.initialize_request(
			self.factory.post("/", {"email": user.email}, format="json")
		)

		response = ForgotPasswordAPIView.post.__wrapped__(view, request)

		self.assertEqual(response.status_code, 200)
		response_data = response.data if isinstance(response.data, dict) else {}
		self.assertNotIn("otp", response_data)
		self.assertTrue(check_password("123456", create_otp.call_args.kwargs["otp"]))
		self.assertIn("123456", send_mail_mock.call_args.kwargs["message"])
		otp_filter.assert_called_once_with(user=user, is_used=False)
		_generate_otp.assert_called_once()
