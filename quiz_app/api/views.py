from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response

from .serializers import QuizCreateSerializer, QuizListSerializer, QuizPatchSerializer, QuizSerializer
from .services import AudioDownloadError
from .transcription import TranscriptionError
from .utils import (
	get_user_owned_quiz,
	quiz_error_response,
	server_error_response,
	QuizNotFound,
	QuizAccessDenied,
)
from quiz_app.models import Quiz


class QuizCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            quizzes = request.user.quizzes.prefetch_related("questions").order_by("-updated_at")
            return Response(QuizListSerializer(quizzes, many=True).data, status=status.HTTP_200_OK)
        except Exception:
            return server_error_response()

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
            return server_error_response()

        return Response(QuizSerializer(quiz).data, status=status.HTTP_201_CREATED)


class QuizDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        try:
            quiz = get_user_owned_quiz(id, request.user)
            return Response(QuizListSerializer(quiz).data, status=status.HTTP_200_OK)
        except (QuizNotFound, QuizAccessDenied) as exc:
            return quiz_error_response(exc)
        except Exception:
            return server_error_response()

    def patch(self, request, id):
        try:
            quiz = get_user_owned_quiz(id, request.user)

            allowed_fields = {"title", "description"}
            provided_fields = set(request.data.keys()) if hasattr(request.data, "keys") else set()
            unsupported_fields = sorted(provided_fields - allowed_fields)
            if unsupported_fields:
                return Response(
                    {"detail": "Only title and description can be updated"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            serializer = QuizPatchSerializer(data=request.data, partial=True)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            for field, value in serializer.validated_data.items():
                setattr(quiz, field, value)
            quiz.save()

            return Response(QuizListSerializer(quiz).data, status=status.HTTP_200_OK)
        except (QuizNotFound, QuizAccessDenied) as exc:
            return quiz_error_response(exc)
        except Exception:
            return server_error_response()

    def delete(self, request, id):
        try:
            quiz = get_user_owned_quiz(id, request.user)
            quiz.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except (QuizNotFound, QuizAccessDenied) as exc:
            return quiz_error_response(exc)
        except Exception:
            return server_error_response()
