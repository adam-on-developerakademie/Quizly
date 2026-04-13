from django.contrib.auth.models import User
from django.conf import settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch
from pathlib import Path
import os

from quiz_app.api.services import AudioDownloadError
from quiz_app.api.transcription import TranscriptionError
from quiz_app.api.transcription import transcribe_audio_file
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
		with patch("quiz_app.api.serializers.download_youtube_audio") as mock_download, patch(
			"quiz_app.api.serializers.transcribe_audio_file"
		) as mock_transcribe:
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
			mock_transcribe.return_value = {
				"text": "Transcribed text",
				"language": "en",
				"segments": [{"id": 0, "start": 0.0, "end": 1.0, "text": "Hello"}],
				"model": "base",
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
		self.assertEqual(quiz.transcript_text, "Transcribed text")
		self.assertEqual(quiz.transcript_language, "en")
		self.assertEqual(quiz.transcript_model, "base")
		self.assertEqual(len(quiz.transcript_segments), 1)

	def test_normalizes_shorts_url_to_watch_format(self):
		self.client.force_authenticate(user=self.user)
		with patch("quiz_app.api.serializers.download_youtube_audio") as mock_download, patch(
			"quiz_app.api.serializers.transcribe_audio_file"
		) as mock_transcribe:
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
			mock_transcribe.return_value = {
				"text": "Short text",
				"language": "en",
				"segments": [],
				"model": "base",
			}
			response = self.client.post(
				self.url,
				{"url": "https://www.youtube.com/shorts/LWrm9PvKYEY"},
				format="json",
			)

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		mock_download.assert_called_once_with("https://www.youtube.com/watch?v=LWrm9PvKYEY")

	def test_repeated_same_video_updates_existing_quiz(self):
		self.client.force_authenticate(user=self.user)
		with patch("quiz_app.api.serializers.download_youtube_audio") as mock_download, patch(
			"quiz_app.api.serializers.transcribe_audio_file"
		) as mock_transcribe:
			mock_download.side_effect = [
				{
					"video_id": "dup123",
					"title": "Initial Title",
					"description": "Initial Description",
					"channel": "Initial Channel",
					"duration_seconds": 111,
					"webpage_url": "https://www.youtube.com/watch?v=dup123",
					"audio_file_name": "quiz_audio/dup123.mp3",
					"audio_filename": "dup123.mp3",
					"audio_filesize_bytes": 1000,
				},
				{
					"video_id": "dup123",
					"title": "Updated Title",
					"description": "Updated Description",
					"channel": "Updated Channel",
					"duration_seconds": 222,
					"webpage_url": "https://www.youtube.com/watch?v=dup123",
					"audio_file_name": "quiz_audio/dup123.mp3",
					"audio_filename": "dup123.mp3",
					"audio_filesize_bytes": 2000,
				},
			]
			mock_transcribe.side_effect = [
				{"text": "First text", "language": "en", "segments": [], "model": "base"},
				{"text": "Second text", "language": "de", "segments": [], "model": "base"},
			]

			first = self.client.post(
				self.url,
				{"url": "https://www.youtube.com/watch?v=dup123"},
				format="json",
			)
			second = self.client.post(
				self.url,
				{"url": "https://www.youtube.com/watch?v=dup123"},
				format="json",
			)

		self.assertEqual(first.status_code, status.HTTP_201_CREATED)
		self.assertEqual(second.status_code, status.HTTP_201_CREATED)
		self.assertEqual(Quiz.objects.count(), 1)
		quiz = Quiz.objects.get()
		self.assertEqual(quiz.title, "Updated Title")
		self.assertEqual(quiz.description, "Updated Description")
		self.assertEqual(quiz.youtube_channel, "Updated Channel")
		self.assertEqual(quiz.youtube_duration_seconds, 222)
		self.assertEqual(quiz.audio_filesize_bytes, 2000)
		self.assertEqual(quiz.transcript_text, "Second text")
		self.assertEqual(quiz.transcript_language, "de")
		self.assertEqual(quiz.questions.count(), 1)

	def test_returns_400_when_audio_download_fails(self):
		self.client.force_authenticate(user=self.user)
		with patch("quiz_app.api.serializers.download_youtube_audio") as mock_download:
			mock_download.side_effect = AudioDownloadError("FFmpeg missing")
			response = self.client.post(
				self.url,
				{"url": "https://www.youtube.com/watch?v=example"},
				format="json",
			)

		self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertEqual(response.data["detail"], "FFmpeg missing")

	def test_returns_500_when_transcription_fails(self):
		self.client.force_authenticate(user=self.user)
		with patch("quiz_app.api.serializers.download_youtube_audio") as mock_download, patch(
			"quiz_app.api.serializers.transcribe_audio_file"
		) as mock_transcribe:
			mock_download.return_value = {
				"video_id": "example",
				"title": "Quiz Title",
				"description": "Quiz Description",
				"channel": "Example Channel",
				"duration_seconds": 123,
				"webpage_url": "https://www.youtube.com/watch?v=example",
				"audio_file_name": "quiz_audio/example.mp3",
				"audio_filename": "example.mp3",
				"audio_filesize_bytes": 1024,
			}
			mock_transcribe.side_effect = TranscriptionError("Could not transcribe audio")
			response = self.client.post(
				self.url,
				{"url": "https://www.youtube.com/watch?v=example"},
				format="json",
			)

		self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
		self.assertEqual(response.data["detail"], "Could not transcribe audio")

	def test_long_video_uses_transcription_time_limit(self):
		self.client.force_authenticate(user=self.user)
		with patch.dict("os.environ", {"WHISPER_TRANSCRIBE_MAX_SECONDS": "600"}, clear=False), patch(
			"quiz_app.api.serializers.download_youtube_audio"
		) as mock_download, patch("quiz_app.api.serializers.transcribe_audio_file") as mock_transcribe:
			mock_download.return_value = {
				"video_id": "longvideo",
				"title": "Long Video",
				"description": "Long video description",
				"channel": "Long Channel",
				"duration_seconds": 941,
				"webpage_url": "https://www.youtube.com/watch?v=3ekrI8syG7E",
				"audio_file_name": "quiz_audio/3ekrI8syG7E.mp3",
				"audio_filename": "3ekrI8syG7E.mp3",
				"audio_filesize_bytes": 4096,
			}
			mock_transcribe.return_value = {
				"text": "Partial transcript",
				"language": "en",
				"segments": [],
				"model": "tiny",
			}

			response = self.client.post(
				self.url,
				{"url": "https://www.youtube.com/watch?v=3ekrI8syG7E"},
				format="json",
			)

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		mock_transcribe.assert_called_once_with("quiz_audio/3ekrI8syG7E.mp3", max_seconds=600)

	def test_transcription_uses_whisper_model_from_env(self):
		audio_rel_path = "quiz_audio/test_tiny_model.mp3"
		audio_abs_path = Path(settings.BASE_DIR) / "media" / audio_rel_path
		audio_abs_path.parent.mkdir(parents=True, exist_ok=True)
		audio_abs_path.write_bytes(b"fake-audio")

		try:
			with patch.dict(os.environ, {"WHISPER_MODEL": "tiny"}, clear=False), patch(
				"quiz_app.api.transcription._load_model"
			) as mock_load_model:
				mock_model = mock_load_model.return_value
				mock_model.transcribe.return_value = {
					"text": "hello tiny model",
					"language": "en",
					"segments": [{"id": 0, "start": 0.0, "end": 1.0, "text": "hello"}],
				}

				result = transcribe_audio_file(audio_rel_path)

			mock_load_model.assert_called_once_with("tiny")
			self.assertEqual(result["model"], "tiny")
			self.assertEqual(result["text"], "hello tiny model")
		finally:
			if audio_abs_path.exists():
				audio_abs_path.unlink()
