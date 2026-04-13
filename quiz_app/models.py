from django.db import models


class Quiz(models.Model):
	title = models.CharField(max_length=255)
	description = models.TextField(blank=True)
	video_url = models.URLField(max_length=500)
	youtube_video_id = models.CharField(max_length=64, blank=True)
	youtube_channel = models.CharField(max_length=255, blank=True)
	youtube_duration_seconds = models.PositiveIntegerField(null=True, blank=True)
	audio_file = models.FileField(upload_to="quiz_audio/", blank=True)
	audio_filename = models.CharField(max_length=255, blank=True)
	audio_filesize_bytes = models.BigIntegerField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self):
		return self.title


class Question(models.Model):
	quiz = models.ForeignKey(Quiz, related_name="questions", on_delete=models.CASCADE)
	question_title = models.CharField(max_length=500)
	question_options = models.JSONField(default=list)
	answer = models.CharField(max_length=255)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self):
		return self.question_title

# Create your models here.
