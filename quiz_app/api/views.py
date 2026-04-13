from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response

from .serializers import QuizCreateSerializer, QuizListSerializer, QuizSerializer
from .services import AudioDownloadError
from .transcription import TranscriptionError
from quiz_app.models import Quiz


class QuizCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            quizzes = request.user.quizzes.prefetch_related("questions").order_by("-updated_at")
            return Response(QuizListSerializer(quizzes, many=True).data, status=status.HTTP_200_OK)
        except Exception:
            return Response(
                {"detail": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request):
        serializer = QuizCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            quiz = serializer.save(owner=request.user)
        except AudioDownloadError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except TranscriptionError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception:
            return Response(
                {"detail": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(QuizSerializer(quiz).data, status=status.HTTP_201_CREATED)


class QuizDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        try:
            quiz = Quiz.objects.prefetch_related("questions").filter(id=id).first()
            if quiz is None:
                return Response(
                    {"detail": "Quiz not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if quiz.owner_id != request.user.id:
                return Response(
                    {"detail": "Access denied"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            return Response(QuizListSerializer(quiz).data, status=status.HTTP_200_OK)
        except Exception:
            return Response(
                {"detail": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
