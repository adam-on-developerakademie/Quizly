from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from auth_app.models import RevokedToken


class AuthCookieFlowTests(APITestCase):
	def setUp(self):
		self.password = "TestPass123!"
		self.user = User.objects.create_user(
			username="tester",
			email="tester@example.com",
			password=self.password,
		)

	def _login(self):
		return self.client.post(
			reverse("token_obtain_pair"),
			{"email": self.user.email, "password": self.password},
			format="json",
		)

	def test_login_hello_logout_then_hello_is_forbidden(self):
		login_response = self._login()
		self.assertEqual(login_response.status_code, status.HTTP_200_OK)
		self.assertIn("access_token", login_response.cookies)
		self.assertIn("refresh_token", login_response.cookies)

		hello_response = self.client.get(reverse("hello"))
		self.assertEqual(hello_response.status_code, status.HTTP_200_OK)
		self.assertIn("access_token_info", hello_response.data)
		self.assertIn("refresh_token_info", hello_response.data)
		self.assertIsNotNone(hello_response.data["access_token_info"]["issued_at"])
		self.assertIsNotNone(hello_response.data["access_token_info"]["expires_at"])
		self.assertGreaterEqual(hello_response.data["access_token_info"]["remaining_seconds"], 0)
		self.assertIsNotNone(hello_response.data["refresh_token_info"]["issued_at"])
		self.assertIsNotNone(hello_response.data["refresh_token_info"]["expires_at"])
		self.assertGreaterEqual(hello_response.data["refresh_token_info"]["remaining_seconds"], 0)

		logout_response = self.client.post(reverse("logout"))
		self.assertEqual(logout_response.status_code, status.HTTP_200_OK)
		self.assertIn("access_token", logout_response.cookies)
		self.assertIn("refresh_token", logout_response.cookies)
		self.assertEqual(logout_response.cookies["access_token"]["max-age"], 0)
		self.assertEqual(logout_response.cookies["refresh_token"]["max-age"], 0)

		revoked_types = set(RevokedToken.objects.values_list("token_type", flat=True))
		self.assertIn("access", revoked_types)
		self.assertIn("refresh", revoked_types)

		post_logout_hello = self.client.get(reverse("hello"))
		self.assertEqual(post_logout_hello.status_code, status.HTTP_401_UNAUTHORIZED)

	def test_refresh_token_cannot_be_reused_after_logout(self):
		login_response = self._login()
		self.assertEqual(login_response.status_code, status.HTTP_200_OK)

		refresh_token = login_response.cookies["refresh_token"].value
		self.client.cookies["refresh_token"] = refresh_token

		logout_response = self.client.post(reverse("logout"))
		self.assertEqual(logout_response.status_code, status.HTTP_200_OK)

		self.client.cookies["refresh_token"] = refresh_token
		refresh_after_logout = self.client.post(reverse("token_refresh"))
		self.assertEqual(refresh_after_logout.status_code, status.HTTP_400_BAD_REQUEST)

	def test_tampered_access_cookie_is_rejected(self):
		self.client.cookies["access_token"] = "tampered.invalid.jwt"
		hello_response = self.client.get(reverse("hello"))
		self.assertEqual(hello_response.status_code, status.HTTP_401_UNAUTHORIZED)

	def test_tampered_refresh_cookie_is_rejected(self):
		self.client.cookies["refresh_token"] = "tampered.invalid.jwt"
		refresh_response = self.client.post(reverse("token_refresh"))
		self.assertEqual(refresh_response.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertIn("error", refresh_response.data)

	def test_registration_with_invalid_cookie_still_works(self):
		self.client.cookies["access_token"] = "tampered.invalid.jwt"
		registration_response = self.client.post(
			reverse("registration"),
			{
				"username": "new_user",
				"email": "new_user@example.com",
				"password": "AnotherPass123!",
				"repeated_password": "AnotherPass123!",
			},
			format="json",
		)

		self.assertEqual(registration_response.status_code, status.HTTP_200_OK)
		self.assertTrue(User.objects.filter(email="new_user@example.com").exists())

	def test_registration_is_blocked_while_authenticated(self):
		login_response = self._login()
		self.assertEqual(login_response.status_code, status.HTTP_200_OK)

		registration_response = self.client.post(
			reverse("registration"),
			{
				"username": "blocked_user",
				"email": "blocked_user@example.com",
				"password": "AnotherPass123!",
				"repeated_password": "AnotherPass123!",
			},
			format="json",
		)

		self.assertEqual(registration_response.status_code, status.HTTP_403_FORBIDDEN)
		self.assertFalse(User.objects.filter(email="blocked_user@example.com").exists())
