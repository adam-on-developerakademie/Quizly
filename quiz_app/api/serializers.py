"""Serializers for quiz creation, listing, and partial updates."""

import os
from urllib.parse import parse_qs, urlparse

from rest_framework import serializers

from quiz_app.models import Question, Quiz
from .services import (
    delete_downloaded_audio,
    download_youtube_audio,
    transcribe_audio_file,
)
from .quiz_generation import generate_quiz_from_transcript


class QuestionSerializer(serializers.ModelSerializer):
    """Serialize full question details for quiz detail responses."""

    class Meta:
        model = Question
        fields = [
            "id",
            "question_title",
            "question_options",
            "answer",
            "created_at",
            "updated_at",
        ]


class QuestionListSerializer(serializers.ModelSerializer):
    """Serialize compact question fields for list-style quiz responses."""

    class Meta:
        model = Question
        fields = [
            "id",
            "question_title",
            "question_options",
            "answer",
        ]


class QuizListSerializer(serializers.ModelSerializer):
    """Serialize quizzes with nested compact question payloads."""

    questions = QuestionListSerializer(many=True, read_only=True)

    class Meta:
        model = Quiz
        fields = [
            "id",
            "title",
            "description",
            "created_at",
            "updated_at",
            "video_url",
            "questions",
        ]


class QuizSerializer(serializers.ModelSerializer):
    """Serialize a quiz including AI generation metadata."""

    questions = QuestionSerializer(many=True, read_only=True)
    ai_response = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = [
            "id",
            "title",
            "description",
            "created_at",
            "updated_at",
            "video_url",
            "ai_status",
            "ai_response",
            "questions",
        ]

    def get_ai_response(self, obj):
        """Return grouped AI metadata as a stable response object."""
        return {
            "model": obj.ai_generation_model,
            "raw_text": obj.ai_response_text,
            "parsed_json": obj.ai_response_json,
            "error": obj.ai_error_message,
        }


class QuizCreateSerializer(serializers.Serializer):
    """Validate a YouTube URL and create or refresh a generated quiz."""

    url = serializers.URLField()

    def validate_url(self, value):
        """Normalize supported YouTube URL formats to one canonical URL.

        The ``www.`` prefix is stripped first so that all hostname variants
        (``www.``, ``m.``, ``youtube-nocookie.com``) are handled by the same
        checks. Watch URLs, ``/shorts/``, ``/embed/``, and ``youtu.be`` short
        links are all accepted. Every supported format is rewritten to the
        canonical form ``https://www.youtube.com/watch?v=<id>``.
        """
        parsed = urlparse(value)
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]

        video_id = None

        if host in {"youtube.com", "m.youtube.com", "youtube-nocookie.com"}:
            if parsed.path == "/watch":
                video_id = parse_qs(parsed.query).get("v", [None])[0]
            elif parsed.path.startswith("/shorts/"):
                video_id = parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else None
            elif parsed.path.startswith("/embed/"):
                video_id = parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else None
        elif host == "youtu.be":
            video_id = parsed.path.lstrip("/").split("/")[0]

        if not video_id:
            raise serializers.ValidationError("Invalid YouTube URL")

        return f"https://www.youtube.com/watch?v={video_id}"

    def create(self, validated_data):
        """Generate quiz content from YouTube audio and persist questions.

        Deduplication is performed in two steps: the database is searched
        first by the stable YouTube video ID, then by the page URL for
        records created before the video ID field was introduced. When an
        existing quiz is found it is updated in place; otherwise a new
        record is created.

        The downloaded audio file is always removed in the ``finally`` block
        regardless of success or failure. Audio data is deliberately not
        persisted on disk after transcription.
        """
        owner = validated_data.pop("owner", None)
        video_url = validated_data["url"]
        audio_data = download_youtube_audio(video_url)
        try:
            transcribe_max_seconds = int(os.getenv("WHISPER_TRANSCRIBE_MAX_SECONDS", "300"))
            transcript_data = transcribe_audio_file(
                audio_data["audio_file_name"],
                max_seconds=transcribe_max_seconds,
            )
            generated_quiz = generate_quiz_from_transcript(
                transcript_data.get("text", ""),
                audio_data.get("title", "the video"),
                audio_data.get("description") or "Auto-generated quiz based on the provided YouTube URL.",
            )
            existing_quiz = Quiz.objects.filter(owner=owner, youtube_video_id=audio_data["video_id"]).first()

            if existing_quiz is None:
                existing_quiz = Quiz.objects.filter(owner=owner, video_url=audio_data["webpage_url"]).first()

            if existing_quiz is None:
                quiz = Quiz.objects.create(
                    owner=owner,
                    title=generated_quiz["title"],
                    description=generated_quiz["description"],
                    video_url=audio_data["webpage_url"],
                    youtube_video_id=audio_data["video_id"],
                    youtube_channel=audio_data["channel"],
                    youtube_duration_seconds=audio_data["duration_seconds"],
                    audio_file="",
                    audio_filename="",
                    audio_filesize_bytes=None,
                    transcript_text=transcript_data["text"],
                    transcript_language=transcript_data["language"],
                    transcript_segments=transcript_data["segments"],
                    transcript_model=transcript_data["model"],
                    ai_response_text=generated_quiz.get("raw_response_text", ""),
                    ai_response_json=generated_quiz.get("raw_response_json", {}),
                    ai_generation_model=generated_quiz.get("ai_model", ""),
                    ai_status=generated_quiz.get("ai_status", ""),
                    ai_error_message=generated_quiz.get("ai_error_message", ""),
                )
            else:
                quiz = existing_quiz
                quiz.owner = owner
                quiz.title = generated_quiz["title"]
                quiz.description = generated_quiz["description"]
                quiz.video_url = audio_data["webpage_url"]
                quiz.youtube_video_id = audio_data["video_id"]
                quiz.youtube_channel = audio_data["channel"]
                quiz.youtube_duration_seconds = audio_data["duration_seconds"]
                quiz.audio_file = ""
                quiz.audio_filename = ""
                quiz.audio_filesize_bytes = None
                quiz.transcript_text = transcript_data["text"]
                quiz.transcript_language = transcript_data["language"]
                quiz.transcript_segments = transcript_data["segments"]
                quiz.transcript_model = transcript_data["model"]
                quiz.ai_response_text = generated_quiz.get("raw_response_text", "")
                quiz.ai_response_json = generated_quiz.get("raw_response_json", {})
                quiz.ai_generation_model = generated_quiz.get("ai_model", "")
                quiz.ai_status = generated_quiz.get("ai_status", "")
                quiz.ai_error_message = generated_quiz.get("ai_error_message", "")
                quiz.save()

            quiz.questions.all().delete()

            for item in generated_quiz["questions"]:
                Question.objects.create(
                    quiz=quiz,
                    question_title=item["question_title"],
                    question_options=item["question_options"],
                    answer=item["answer"],
                )

            return quiz
        finally:
            delete_downloaded_audio(audio_data.get("audio_file_name"))


class QuizPatchSerializer(serializers.Serializer):
    """Validate editable quiz fields for partial updates."""

    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        """Reject empty PATCH payloads.

        At least one of ``title`` or ``description`` must be present in the
        request body; an empty object is treated as a client error.
        """
        if not attrs:
            raise serializers.ValidationError("No fields provided for update")
        return attrs
