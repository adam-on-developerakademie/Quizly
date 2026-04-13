from urllib.parse import parse_qs, urlparse
import os

from rest_framework import serializers

from quiz_app.models import Question, Quiz
from .services import download_youtube_audio
from .transcription import transcribe_audio_file
from .quiz_generation import generate_quiz_from_transcript


class QuestionSerializer(serializers.ModelSerializer):
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


class QuizSerializer(serializers.ModelSerializer):
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
        return {
            "model": obj.ai_generation_model,
            "raw_text": obj.ai_response_text,
            "parsed_json": obj.ai_response_json,
            "error": obj.ai_error_message,
        }


class QuizCreateSerializer(serializers.Serializer):
    url = serializers.URLField()

    def validate_url(self, value):
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
        video_url = validated_data["url"]
        audio_data = download_youtube_audio(video_url)
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
        existing_quiz = Quiz.objects.filter(youtube_video_id=audio_data["video_id"]).first()

        if existing_quiz is None:
            existing_quiz = Quiz.objects.filter(video_url=audio_data["webpage_url"]).first()

        if existing_quiz is None:
            quiz = Quiz.objects.create(
                title=generated_quiz["title"],
                description=generated_quiz["description"],
                video_url=audio_data["webpage_url"],
                youtube_video_id=audio_data["video_id"],
                youtube_channel=audio_data["channel"],
                youtube_duration_seconds=audio_data["duration_seconds"],
                audio_file=audio_data["audio_file_name"],
                audio_filename=audio_data["audio_filename"],
                audio_filesize_bytes=audio_data["audio_filesize_bytes"],
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
            quiz.title = generated_quiz["title"]
            quiz.description = generated_quiz["description"]
            quiz.video_url = audio_data["webpage_url"]
            quiz.youtube_video_id = audio_data["video_id"]
            quiz.youtube_channel = audio_data["channel"]
            quiz.youtube_duration_seconds = audio_data["duration_seconds"]
            quiz.audio_file = audio_data["audio_file_name"]
            quiz.audio_filename = audio_data["audio_filename"]
            quiz.audio_filesize_bytes = audio_data["audio_filesize_bytes"]
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
