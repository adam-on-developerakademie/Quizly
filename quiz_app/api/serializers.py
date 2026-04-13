from urllib.parse import parse_qs, urlparse

from rest_framework import serializers

from quiz_app.models import Question, Quiz
from .services import download_youtube_audio


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
        quiz = Quiz.objects.create(
            title=audio_data["title"],
            description=audio_data["description"] or "Auto-generated quiz based on the provided YouTube URL.",
            video_url=audio_data["webpage_url"],
            youtube_video_id=audio_data["video_id"],
            youtube_channel=audio_data["channel"],
            youtube_duration_seconds=audio_data["duration_seconds"],
            audio_file=audio_data["audio_file_name"],
            audio_filename=audio_data["audio_filename"],
            audio_filesize_bytes=audio_data["audio_filesize_bytes"],
        )

        Question.objects.create(
            quiz=quiz,
            question_title="What is the main topic of the video?",
            question_options=["Option A", "Option B", "Option C", "Option D"],
            answer="Option A",
        )

        return quiz
