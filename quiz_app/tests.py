from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quiz_app.models import Quiz


class QuizCreateApiTests(APITestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			username="quiz_user",
			email="quiz_user@example.com",
			password="QuizPass123!",
		)
		self.url = reverse("quiz-create")

	def test_requires_authentication(self):
		response = self.client.post(
			self.url,
			{"url": "https://www.youtube.com/watch?v=example"},
			format="json",
		)
		self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

	def test_returns_400_for_invalid_url(self):
		self.client.force_authenticate(user=self.user)
		response = self.client.post(
			self.url,
			{"url": "https://example.com/not-youtube"},
			format="json",
		)
		self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

	def test_creates_quiz_and_returns_questions(self):
		self.client.force_authenticate(user=self.user)
		response = self.client.post(
			self.url,
			{"url": "https://www.youtube.com/watch?v=example"},
			format="json",
		)

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		self.assertIn("id", response.data)
		self.assertEqual(response.data["video_url"], "https://www.youtube.com/watch?v=example")
		self.assertIn("created_at", response.data)
		self.assertIn("updated_at", response.data)
		self.assertIn("questions", response.data)
		self.assertEqual(len(response.data["questions"]), 1)

		question = response.data["questions"][0]
		self.assertIn("id", question)
		self.assertIn("question_title", question)
		self.assertIn("question_options", question)
		self.assertEqual(len(question["question_options"]), 4)
		self.assertIn("answer", question)
		self.assertIn("created_at", question)
		self.assertIn("updated_at", question)

		self.assertEqual(Quiz.objects.count(), 1)
