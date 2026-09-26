from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory

from gaming.views import GoogleCodeLoginView


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
