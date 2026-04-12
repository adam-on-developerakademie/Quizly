from urllib.parse import urlparse

from rest_framework import serializers

from quiz_app.models import Question, Quiz


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

        is_youtube = host in {"youtube.com", "youtu.be"}
        has_video_path = parsed.path == "/watch" or host == "youtu.be"

        if not is_youtube or not has_video_path:
            raise serializers.ValidationError("Invalid YouTube URL")
        return value

    def create(self, validated_data):
        video_url = validated_data["url"]
        quiz = Quiz.objects.create(
            title="Quiz from YouTube Video",
            description="Auto-generated quiz based on the provided YouTube URL.",
            video_url=video_url,
        )

        Question.objects.create(
            quiz=quiz,
            question_title="What is the main topic of the video?",
            question_options=["Option A", "Option B", "Option C", "Option D"],
            answer="Option A",
        )

        return quiz
