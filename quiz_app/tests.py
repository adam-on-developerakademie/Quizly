from django.contrib.auth.models import User
from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch
from pathlib import Path
import os
import json

from quiz_app.api.services import AudioDownloadError
from quiz_app.api.quiz_generation import generate_quiz_from_transcript
from quiz_app.api.transcription import TranscriptionError
from quiz_app.api.transcription import transcribe_audio_file
from quiz_app.models import Quiz


class QuizGenerationTests(SimpleTestCase):
	def _build_ten_questions(self):
		questions = []
		for i in range(1, 11):
			questions.append(
				{
					"question_title": f"Question {i}",
					"question_options": [f"A{i}", f"B{i}", f"C{i}", f"D{i}"],
					"answer": f"A{i}",
				}
			)
		return questions

	def test_parses_markdown_fenced_json_response(self):
		payload = {
			"title": "AI Quiz Title",
			"description": "Short summary",
			"questions": self._build_ten_questions(),
		}
		fenced_text = "```json\n" + json.dumps(payload) + "\n```"

		with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}, clear=False), patch(
			"google.genai.Client"
		) as mock_client:
			mock_client.return_value.models.generate_content.return_value.text = fenced_text
			result = generate_quiz_from_transcript("Transcript", "Topic", "Desc")

		self.assertEqual(result["title"], "AI Quiz Title")
		self.assertEqual(result["description"], "Short summary")
		self.assertEqual(len(result["questions"]), 10)
		self.assertEqual(result["ai_status"], "ok")

	def test_returns_fallback_when_ai_returns_invalid_json(self):
		with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}, clear=False), patch(
			"google.genai.Client"
		) as mock_client:
			mock_client.return_value.models.generate_content.return_value.text = "```json\nnot valid json\n```"
			result = generate_quiz_from_transcript("Transcript", "Topic", "Desc")

		self.assertTrue(result["title"].startswith("Quiz: Topic"))
		self.assertEqual(len(result["questions"]), 10)

	def test_returns_fallback_when_less_than_ten_questions(self):
		payload = {
			"title": "Too Short Quiz",
			"description": "Summary",
			"questions": [
				{
					"question_title": "Only one",
					"question_options": ["A", "B", "C", "D"],
					"answer": "A",
				}
			],
		}

		with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}, clear=False), patch(
			"google.genai.Client"
		) as mock_client:
			mock_client.return_value.models.generate_content.return_value.text = json.dumps(payload)
			result = generate_quiz_from_transcript("Transcript", "Topic", "Desc")

		self.assertTrue(result["title"].startswith("Quiz: Topic"))
		self.assertEqual(len(result["questions"]), 10)

	def test_parses_json_when_model_adds_extra_text(self):
		payload = {
			"title": "Wrapped Quiz",
			"description": "Wrapped summary",
			"questions": self._build_ten_questions(),
		}
		wrapped_text = "Here is your quiz output:\n" + json.dumps(payload) + "\nHope this helps."

		with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}, clear=False), patch(
			"google.genai.Client"
		) as mock_client:
			mock_client.return_value.models.generate_content.return_value.text = wrapped_text
			result = generate_quiz_from_transcript("Transcript", "Topic", "Desc")

		self.assertEqual(result["title"], "Wrapped Quiz")
		self.assertEqual(result["description"], "Wrapped summary")
		self.assertEqual(len(result["questions"]), 10)

	def test_oversized_model_response_uses_fallback(self):
		payload = {
			"title": "Very Long",
			"description": "Summary",
			"questions": self._build_ten_questions(),
		}
		wrapped_text = "prefix " + json.dumps(payload)

		with patch.dict(
			"os.environ",
			{"GOOGLE_API_KEY": "test-key", "GOOGLE_GENAI_MAX_RESPONSE_CHARS": "40"},
			clear=False,
		), patch("google.genai.Client") as mock_client:
			mock_client.return_value.models.generate_content.return_value.text = wrapped_text
			result = generate_quiz_from_transcript("Transcript", "Topic", "Desc")

		self.assertTrue(result["title"].startswith("Quiz: Topic"))
		self.assertEqual(len(result["questions"]), 10)

	def test_quota_error_returns_no_credits_fallback_text(self):
		with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}, clear=False), patch(
			"google.genai.Client"
		) as mock_client:
			mock_client.return_value.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED quota exceeded")
			result = generate_quiz_from_transcript("Transcript", "Topic", "Desc")

		self.assertEqual(result["title"], "AI credits unavailable")
		self.assertIn("No AI credits available", result["description"])
		self.assertEqual(len(result["questions"]), 10)
		self.assertIn("no credits", result["questions"][0]["question_title"].lower())
		self.assertEqual(result["ai_status"], "no_credits")
		self.assertIn("RESOURCE_EXHAUSTED", result["ai_error_message"].upper())

	def test_model_not_found_uses_fallback_model(self):
		payload = {
			"title": "Fallback Model Quiz",
			"description": "Summary",
			"questions": self._build_ten_questions(),
		}

		with patch.dict(
			"os.environ",
			{
				"GOOGLE_API_KEY": "test-key",
				"GOOGLE_GENAI_MODEL": "models/invalid-preview-model",
				"GOOGLE_GENAI_FALLBACK_MODEL": "models/gemini-2.5-flash-lite",
			},
			clear=False,
		), patch("google.genai.Client") as mock_client:
			mock_client.return_value.models.generate_content.side_effect = [
				Exception("404 NOT_FOUND model not found"),
				type("Resp", (), {"text": json.dumps(payload)})(),
			]
			result = generate_quiz_from_transcript("Transcript", "Topic", "Desc")

		self.assertEqual(result["title"], "Fallback Model Quiz")
		self.assertEqual(result["ai_status"], "ok_with_model_fallback")
		self.assertEqual(result["ai_model"], "models/gemini-2.5-flash-lite")


class QuizCreateApiTests(APITestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			username="quiz_user",
			email="quiz_user@example.com",
			password="QuizPass123!",
		)
		self.other_user = User.objects.create_user(
			username="other_user",
			email="other_user@example.com",
			password="OtherPass123!",
		)
		self.url = reverse("quiz-create")
		self.detail_url = lambda quiz_id: reverse("quiz-detail", kwargs={"id": quiz_id})

	def test_get_requires_authentication(self):
		response = self.client.get(self.url)
		self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

	def test_get_returns_only_authenticated_users_quizzes(self):
		own_quiz = Quiz.objects.create(
			owner=self.user,
			title="Own Quiz",
			description="Own Description",
			video_url="https://www.youtube.com/watch?v=own1",
		)
		other_quiz = Quiz.objects.create(
			owner=self.other_user,
			title="Other Quiz",
			description="Other Description",
			video_url="https://www.youtube.com/watch?v=other1",
		)
		Quiz.objects.create(
			title="No Owner Quiz",
			description="No owner",
			video_url="https://www.youtube.com/watch?v=none1",
		)
		own_quiz.questions.create(
			question_title="Question 1",
			question_options=["A", "B", "C", "D"],
			answer="A",
		)
		other_quiz.questions.create(
			question_title="Other Question",
			question_options=["A", "B", "C", "D"],
			answer="A",
		)

		self.client.force_authenticate(user=self.user)
		response = self.client.get(self.url)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(len(response.data), 1)
		payload = response.data[0]
		self.assertEqual(payload["title"], "Own Quiz")
		self.assertEqual(payload["video_url"], "https://www.youtube.com/watch?v=own1")
		self.assertIn("created_at", payload)
		self.assertIn("updated_at", payload)
		self.assertIn("questions", payload)
		self.assertEqual(len(payload["questions"]), 1)
		q = payload["questions"][0]
		self.assertIn("id", q)
		self.assertIn("question_title", q)
		self.assertIn("question_options", q)
		self.assertIn("answer", q)
		self.assertNotIn("created_at", q)
		self.assertNotIn("updated_at", q)

	def test_get_detail_requires_authentication(self):
		quiz = Quiz.objects.create(
			owner=self.user,
			title="Own Quiz",
			description="Own Description",
			video_url="https://www.youtube.com/watch?v=own1",
		)
		response = self.client.get(self.detail_url(quiz.id))
		self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

	def test_get_detail_returns_404_when_quiz_not_found(self):
		self.client.force_authenticate(user=self.user)
		response = self.client.get(self.detail_url(999999))
		self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

	def test_get_detail_returns_403_for_foreign_quiz(self):
		quiz = Quiz.objects.create(
			owner=self.other_user,
			title="Other Quiz",
			description="Other Description",
			video_url="https://www.youtube.com/watch?v=other1",
		)
		self.client.force_authenticate(user=self.user)
		response = self.client.get(self.detail_url(quiz.id))
		self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

	def test_get_detail_returns_quiz_for_owner(self):
		quiz = Quiz.objects.create(
			owner=self.user,
			title="Detail Quiz",
			description="Detail Description",
			video_url="https://www.youtube.com/watch?v=detail1",
		)
		quiz.questions.create(
			question_title="Detail Question",
			question_options=["A", "B", "C", "D"],
			answer="A",
		)

		self.client.force_authenticate(user=self.user)
		response = self.client.get(self.detail_url(quiz.id))

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data["id"], quiz.id)
		self.assertEqual(response.data["title"], "Detail Quiz")
		self.assertEqual(response.data["description"], "Detail Description")
		self.assertEqual(response.data["video_url"], "https://www.youtube.com/watch?v=detail1")
		self.assertIn("created_at", response.data)
		self.assertIn("updated_at", response.data)
		self.assertIn("questions", response.data)
		self.assertEqual(len(response.data["questions"]), 1)
		self.assertEqual(response.data["questions"][0]["question_title"], "Detail Question")
		self.assertIn("question_options", response.data["questions"][0])
		self.assertIn("answer", response.data["questions"][0])

	def test_patch_detail_requires_authentication(self):
		quiz = Quiz.objects.create(
			owner=self.user,
			title="Detail Quiz",
			description="Detail Description",
			video_url="https://www.youtube.com/watch?v=detail1",
		)
		response = self.client.patch(self.detail_url(quiz.id), {"title": "New"}, format="json")
		self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

	def test_patch_detail_returns_404_when_quiz_not_found(self):
		self.client.force_authenticate(user=self.user)
		response = self.client.patch(self.detail_url(999999), {"title": "New"}, format="json")
		self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

	def test_patch_detail_returns_403_for_foreign_quiz(self):
		quiz = Quiz.objects.create(
			owner=self.other_user,
			title="Other Quiz",
			description="Other Description",
			video_url="https://www.youtube.com/watch?v=other1",
		)
		self.client.force_authenticate(user=self.user)
		response = self.client.patch(self.detail_url(quiz.id), {"title": "New"}, format="json")
		self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

	def test_patch_detail_returns_400_for_invalid_payload(self):
		quiz = Quiz.objects.create(
			owner=self.user,
			title="Detail Quiz",
			description="Detail Description",
			video_url="https://www.youtube.com/watch?v=detail1",
		)
		self.client.force_authenticate(user=self.user)
		response = self.client.patch(self.detail_url(quiz.id), {}, format="json")
		self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

	def test_patch_detail_returns_400_for_unsupported_fields(self):
		quiz = Quiz.objects.create(
			owner=self.user,
			title="Detail Quiz",
			description="Detail Description",
			video_url="https://www.youtube.com/watch?v=detail1",
		)
		self.client.force_authenticate(user=self.user)
		response = self.client.patch(self.detail_url(quiz.id), {"video_url": "https://x"}, format="json")
		self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertEqual(response.data["detail"], "Only title and description can be updated")

	def test_patch_detail_updates_selected_fields(self):
		quiz = Quiz.objects.create(
			owner=self.user,
			title="Original Title",
			description="Original Description",
			video_url="https://www.youtube.com/watch?v=detail1",
		)
		quiz.questions.create(
			question_title="Detail Question",
			question_options=["A", "B", "C", "D"],
			answer="A",
		)

		self.client.force_authenticate(user=self.user)
		response = self.client.patch(
			self.detail_url(quiz.id),
			{"title": "Partially Updated Title", "description": "Partially Updated Description"},
			format="json",
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data["id"], quiz.id)
		self.assertEqual(response.data["title"], "Partially Updated Title")
		self.assertEqual(response.data["description"], "Partially Updated Description")
		self.assertEqual(response.data["video_url"], "https://www.youtube.com/watch?v=detail1")
		self.assertIn("created_at", response.data)
		self.assertIn("updated_at", response.data)
		self.assertEqual(len(response.data["questions"]), 1)
		self.assertEqual(response.data["questions"][0]["question_title"], "Detail Question")

		quiz.refresh_from_db()
		self.assertEqual(quiz.title, "Partially Updated Title")
		self.assertEqual(quiz.description, "Partially Updated Description")

	def test_delete_detail_requires_authentication(self):
		quiz = Quiz.objects.create(
			owner=self.user,
			title="Delete Quiz",
			description="Delete Description",
			video_url="https://www.youtube.com/watch?v=delete1",
		)
		response = self.client.delete(self.detail_url(quiz.id))
		self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

	def test_delete_detail_returns_404_when_quiz_not_found(self):
		self.client.force_authenticate(user=self.user)
		response = self.client.delete(self.detail_url(999999))
		self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

	def test_delete_detail_returns_403_for_foreign_quiz(self):
		quiz = Quiz.objects.create(
			owner=self.other_user,
			title="Other Quiz",
			description="Other Description",
			video_url="https://www.youtube.com/watch?v=other1",
		)
		self.client.force_authenticate(user=self.user)
		response = self.client.delete(self.detail_url(quiz.id))
		self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

	def test_delete_detail_removes_quiz_and_questions(self):
		quiz = Quiz.objects.create(
			owner=self.user,
			title="Delete Quiz",
			description="Delete Description",
			video_url="https://www.youtube.com/watch?v=delete1",
		)
		quiz.questions.create(
			question_title="Question to delete",
			question_options=["A", "B", "C", "D"],
			answer="A",
		)

		self.client.force_authenticate(user=self.user)
		response = self.client.delete(self.detail_url(quiz.id))

		self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
		self.assertFalse(Quiz.objects.filter(id=quiz.id).exists())

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
		) as mock_transcribe, patch("quiz_app.api.serializers.generate_quiz_from_transcript") as mock_generate:
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
			mock_generate.return_value = {
				"title": "Generated Quiz Title",
				"description": "Generated summary",
				"raw_response_text": "{\"title\":\"Generated Quiz Title\"}",
				"raw_response_json": {"title": "Generated Quiz Title", "description": "Generated summary"},
				"ai_model": "gemini-2.0-flash",
				"ai_status": "ok",
				"ai_error_message": "",
				"questions": [
					{
						"question_title": "What is discussed in the transcript?",
						"question_options": ["A", "B", "C", "D"],
						"answer": "A",
					}
				],
			}
			response = self.client.post(
				self.url,
				{"url": "https://www.youtube.com/watch?v=example"},
				format="json",
			)

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		self.assertIn("id", response.data)
		self.assertEqual(response.data["title"], "Generated Quiz Title")
		self.assertEqual(response.data["description"], "Generated summary")
		self.assertEqual(response.data["video_url"], "https://www.youtube.com/watch?v=example")
		self.assertIn("created_at", response.data)
		self.assertIn("updated_at", response.data)
		self.assertIn("questions", response.data)
		self.assertEqual(response.data["ai_status"], "ok")
		self.assertIn("ai_response", response.data)
		self.assertEqual(response.data["ai_response"]["model"], "gemini-2.0-flash")
		self.assertEqual(response.data["ai_response"]["parsed_json"]["title"], "Generated Quiz Title")
		self.assertEqual(len(response.data["questions"]), 1)
		self.assertNotIn("transcript_text", response.data)
		self.assertNotIn("transcript_language", response.data)
		self.assertNotIn("transcript_segments", response.data)
		self.assertNotIn("transcript_model", response.data)
		self.assertNotIn("youtube_video_id", response.data)
		self.assertNotIn("audio_file", response.data)

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
		self.assertEqual(quiz.owner, self.user)
		self.assertEqual(quiz.youtube_video_id, "example")
		self.assertEqual(quiz.youtube_channel, "Example Channel")
		self.assertEqual(quiz.youtube_duration_seconds, 123)
		# Audio files are deleted after transcription, so these should be empty/null
		self.assertEqual(quiz.audio_file.name, "")
		self.assertEqual(quiz.audio_filename, "")
		self.assertIsNone(quiz.audio_filesize_bytes)
		self.assertEqual(quiz.transcript_text, "Transcribed text")
		self.assertEqual(quiz.transcript_language, "en")
		self.assertEqual(quiz.transcript_model, "base")
		self.assertEqual(len(quiz.transcript_segments), 1)
		self.assertEqual(quiz.ai_response_text, "{\"title\":\"Generated Quiz Title\"}")
		self.assertEqual(quiz.ai_response_json["title"], "Generated Quiz Title")
		self.assertEqual(quiz.ai_generation_model, "gemini-2.0-flash")
		self.assertEqual(quiz.ai_status, "ok")
		self.assertEqual(quiz.ai_error_message, "")

	def test_uses_generated_question_set_from_transcript(self):
		self.client.force_authenticate(user=self.user)
		with patch("quiz_app.api.serializers.download_youtube_audio") as mock_download, patch(
			"quiz_app.api.serializers.transcribe_audio_file"
		) as mock_transcribe, patch("quiz_app.api.serializers.generate_quiz_from_transcript") as mock_generate:
			mock_download.return_value = {
				"video_id": "genai01",
				"title": "AI Title",
				"description": "AI Description",
				"channel": "AI Channel",
				"duration_seconds": 88,
				"webpage_url": "https://www.youtube.com/watch?v=genai01",
				"audio_file_name": "quiz_audio/genai01.mp3",
				"audio_filename": "genai01.mp3",
				"audio_filesize_bytes": 1234,
			}
			mock_transcribe.return_value = {
				"text": "Transcript from video",
				"language": "en",
				"segments": [],
				"model": "tiny",
			}
			mock_generate.return_value = {
				"title": "AI Quiz",
				"description": "AI summary",
				"questions": [
					{
						"question_title": "Question 1",
						"question_options": ["A1", "B1", "C1", "D1"],
						"answer": "A1",
					},
					{
						"question_title": "Question 2",
						"question_options": ["A2", "B2", "C2", "D2"],
						"answer": "B2",
					},
				],
			}

			response = self.client.post(
				self.url,
				{"url": "https://www.youtube.com/watch?v=genai01"},
				format="json",
			)

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		self.assertEqual(len(response.data["questions"]), 2)
		mock_generate.assert_called_once_with("Transcript from video", "AI Title", "AI Description")

	def test_normalizes_shorts_url_to_watch_format(self):
		self.client.force_authenticate(user=self.user)
		with patch("quiz_app.api.serializers.download_youtube_audio") as mock_download, patch(
			"quiz_app.api.serializers.transcribe_audio_file"
		) as mock_transcribe, patch("quiz_app.api.serializers.generate_quiz_from_transcript") as mock_generate:
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
			mock_generate.return_value = {
				"title": "Short Quiz",
				"description": "Short summary",
				"questions": [
					{
						"question_title": "Q",
						"question_options": ["A", "B", "C", "D"],
						"answer": "A",
					}
				],
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
		) as mock_transcribe, patch("quiz_app.api.serializers.generate_quiz_from_transcript") as mock_generate:
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
			mock_generate.side_effect = [
				{
					"title": "First Generated Title",
					"description": "First Generated Description",
					"questions": [
						{
							"question_title": "First Question",
							"question_options": ["A", "B", "C", "D"],
							"answer": "A",
						}
					],
				},
				{
					"title": "Second Generated Title",
					"description": "Second Generated Description",
					"questions": [
						{
							"question_title": "Second Question",
							"question_options": ["A", "B", "C", "D"],
							"answer": "B",
						}
					],
				},
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
		self.assertEqual(quiz.title, "Second Generated Title")
		self.assertEqual(quiz.description, "Second Generated Description")
		self.assertEqual(quiz.youtube_channel, "Updated Channel")
		self.assertEqual(quiz.youtube_duration_seconds, 222)
		# Audio files are deleted after transcription, so filesize should be null
		self.assertIsNone(quiz.audio_filesize_bytes)
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
		) as mock_transcribe, patch("quiz_app.api.serializers.generate_quiz_from_transcript") as mock_generate:
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
			mock_generate.return_value = {
				"title": "Q",
				"description": "Q",
				"questions": [
					{
						"question_title": "Q",
						"question_options": ["A", "B", "C", "D"],
						"answer": "A",
					}
				],
			}
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
		) as mock_download, patch("quiz_app.api.serializers.transcribe_audio_file") as mock_transcribe, patch(
			"quiz_app.api.serializers.generate_quiz_from_transcript"
		) as mock_generate:
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
			mock_generate.return_value = {
				"title": "Long Quiz",
				"description": "Long summary",
				"questions": [
					{
						"question_title": "Q",
						"question_options": ["A", "B", "C", "D"],
						"answer": "A",
					}
				],
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
