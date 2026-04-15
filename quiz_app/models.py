"""Database models for quizzes and generated questions."""

from django.conf import settings
from django.db import models


class Quiz(models.Model):
	"""Store quiz metadata, transcript data, and AI generation output."""

	owner = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="quizzes",
	)
	title = models.CharField(max_length=255)
	description = models.TextField(blank=True)
	video_url = models.URLField(max_length=500)
	youtube_video_id = models.CharField(max_length=64, blank=True)
	youtube_channel = models.CharField(max_length=255, blank=True)
	youtube_duration_seconds = models.PositiveIntegerField(null=True, blank=True)
	audio_file = models.FileField(upload_to="quiz_audio/", blank=True)
	audio_filename = models.CharField(max_length=255, blank=True)
	audio_filesize_bytes = models.BigIntegerField(null=True, blank=True)
	transcript_text = models.TextField(blank=True)
	transcript_language = models.CharField(max_length=32, blank=True)
	transcript_segments = models.JSONField(default=list, blank=True)
	transcript_model = models.CharField(max_length=64, blank=True)
	ai_response_text = models.TextField(blank=True)
	ai_response_json = models.JSONField(default=dict, blank=True)
	ai_generation_model = models.CharField(max_length=64, blank=True)
	ai_status = models.CharField(max_length=32, blank=True)
	ai_error_message = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self):
		"""Return the quiz title for Django admin displays."""
		return self.title


class Question(models.Model):
	"""Store one multiple-choice question that belongs to a quiz."""

	quiz = models.ForeignKey(Quiz, related_name="questions", on_delete=models.CASCADE)
	question_title = models.CharField(max_length=500)
	question_options = models.JSONField(default=list)
	answer = models.CharField(max_length=255)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self):
		"""Return the question title for Django admin displays."""
		return self.question_title
