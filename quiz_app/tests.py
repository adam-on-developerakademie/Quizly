from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch

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
		with patch("quiz_app.api.serializers.download_youtube_audio") as mock_download:
			mock_download.return_value = {
				"video_id": "example",
				"title": "Quiz Title",
				"description": "Quiz Description",
				"channel": "Example Channel",
				"duration_seconds": 123,
				"webpage_url": "https://www.youtube.com/watch?v=example",
				"audio_file_name": "quiz_audio/example.webm",
				"audio_filename": "example.webm",
				"audio_filesize_bytes": 1024,
			}
			response = self.client.post(
				self.url,
				{"url": "https://www.youtube.com/watch?v=example"},
				format="json",
			)

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		self.assertIn("id", response.data)
		self.assertEqual(response.data["title"], "Quiz Title")
		self.assertEqual(response.data["description"], "Quiz Description")
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
		quiz = Quiz.objects.get()
		self.assertEqual(quiz.youtube_video_id, "example")
		self.assertEqual(quiz.youtube_channel, "Example Channel")
		self.assertEqual(quiz.youtube_duration_seconds, 123)
		self.assertEqual(quiz.audio_file.name, "quiz_audio/example.webm")
		self.assertEqual(quiz.audio_filename, "example.webm")
		self.assertEqual(quiz.audio_filesize_bytes, 1024)

	def test_normalizes_shorts_url_to_watch_format(self):
		self.client.force_authenticate(user=self.user)
		with patch("quiz_app.api.serializers.download_youtube_audio") as mock_download:
			mock_download.return_value = {
				"video_id": "LWrm9PvKYEY",
				"title": "Quiz Title",
				"description": "Quiz Description",
				"channel": "Example Channel",
				"duration_seconds": 123,
				"webpage_url": "https://www.youtube.com/watch?v=LWrm9PvKYEY",
				"audio_file_name": "quiz_audio/LWrm9PvKYEY.webm",
				"audio_filename": "LWrm9PvKYEY.webm",
				"audio_filesize_bytes": 2048,
			}
			response = self.client.post(
				self.url,
				{"url": "https://www.youtube.com/shorts/LWrm9PvKYEY"},
				format="json",
			)

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		mock_download.assert_called_once_with("https://www.youtube.com/watch?v=LWrm9PvKYEY")
