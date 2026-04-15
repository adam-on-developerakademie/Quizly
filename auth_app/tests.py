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
			reverse("login"),
			{"email": self.user.email, "password": self.password},
			format="json",
		)

	def _login_with_username(self):
		return self.client.post(
			reverse("login"),
			{"username": self.user.username, "password": self.password},
			format="json",
		)

	def test_login_protected_endpoint_logout_then_access_is_forbidden(self):
		login_response = self._login()
		self.assertEqual(login_response.status_code, status.HTTP_200_OK)
		self.assertEqual(login_response.data["detail"], "Login successfully!")
		self.assertEqual(login_response.data["user"]["id"], self.user.pk)
		self.assertEqual(login_response.data["user"]["username"], self.user.username)
		self.assertEqual(login_response.data["user"]["email"], self.user.email)
		self.assertIn("access_token", login_response.cookies)
		self.assertIn("refresh_token", login_response.cookies)

		protected_response = self.client.get(reverse("quiz-create"))
		self.assertEqual(protected_response.status_code, status.HTTP_200_OK)

		logout_response = self.client.post(reverse("logout"))
		self.assertEqual(logout_response.status_code, status.HTTP_200_OK)
		self.assertEqual(
			logout_response.data["detail"],
			"Log-Out successfully! All Tokens will be deleted. Refresh token is now invalid.",
		)
		self.assertIn("access_token", logout_response.cookies)
		self.assertIn("refresh_token", logout_response.cookies)
		self.assertEqual(logout_response.cookies["access_token"]["max-age"], 0)
		self.assertEqual(logout_response.cookies["refresh_token"]["max-age"], 0)

		revoked_types = set(RevokedToken.objects.values_list("token_type", flat=True))
		self.assertIn("access", revoked_types)
		self.assertIn("refresh", revoked_types)

		post_logout_protected = self.client.get(reverse("quiz-create"))
		self.assertEqual(post_logout_protected.status_code, status.HTTP_401_UNAUTHORIZED)

	def test_refresh_token_cannot_be_reused_after_logout(self):
		login_response = self._login()
		self.assertEqual(login_response.status_code, status.HTTP_200_OK)

		refresh_token = login_response.cookies["refresh_token"].value
		self.client.cookies["refresh_token"] = refresh_token

		logout_response = self.client.post(reverse("logout"))
		self.assertEqual(logout_response.status_code, status.HTTP_200_OK)
		self.assertEqual(
			logout_response.data["detail"],
			"Log-Out successfully! All Tokens will be deleted. Refresh token is now invalid.",
		)

		self.client.cookies["refresh_token"] = refresh_token
		refresh_after_logout = self.client.post(reverse("token_refresh"))
		self.assertEqual(refresh_after_logout.status_code, status.HTTP_400_BAD_REQUEST)

	def test_refresh_success_response_returns_detail(self):
		login_response = self._login()
		self.assertEqual(login_response.status_code, status.HTTP_200_OK)

		refresh_response = self.client.post(reverse("token_refresh"))
		self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)
		self.assertEqual(refresh_response.data["detail"], "Token refreshed")
		self.assertIn("access_token", refresh_response.cookies)

	def test_tampered_access_cookie_is_rejected(self):
		self.client.cookies["access_token"] = "tampered.invalid.jwt"
		protected_response = self.client.get(reverse("quiz-create"))
		self.assertEqual(protected_response.status_code, status.HTTP_401_UNAUTHORIZED)

	def test_tampered_refresh_cookie_is_rejected(self):
		self.client.cookies["refresh_token"] = "tampered.invalid.jwt"
		refresh_response = self.client.post(reverse("token_refresh"))
		self.assertEqual(refresh_response.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertIn("error", refresh_response.data)

	def test_login_without_email_field_works_with_username(self):
		login_response = self._login_with_username()
		self.assertEqual(login_response.status_code, status.HTTP_200_OK)
		self.assertEqual(login_response.data["detail"], "Login successfully!")
		self.assertEqual(login_response.data["user"]["username"], self.user.username)
		self.assertEqual(login_response.data["user"]["email"], self.user.email)
		self.assertIn("access_token", login_response.cookies)
		self.assertIn("refresh_token", login_response.cookies)

	def test_registration_with_invalid_cookie_still_works(self):
		self.client.cookies["access_token"] = "tampered.invalid.jwt"
		registration_response = self.client.post(
			reverse("registration"),
			{
				"username": "new_user",
				"email": "new_user@example.com",
				"password": "AnotherPass123!",
				"confirmed_password": "AnotherPass123!",
			},
			format="json",
		)

		self.assertEqual(registration_response.status_code, status.HTTP_201_CREATED)
		self.assertEqual(registration_response.data["detail"], "User created successfully!")
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
				"confirmed_password": "AnotherPass123!",
			},
			format="json",
		)

		self.assertEqual(registration_response.status_code, status.HTTP_403_FORBIDDEN)
		self.assertFalse(User.objects.filter(email="blocked_user@example.com").exists())
