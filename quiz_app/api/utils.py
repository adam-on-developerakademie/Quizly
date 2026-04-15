"""Utility helpers for quiz ownership checks and error responses."""

from rest_framework import status
from rest_framework.response import Response

from quiz_app.models import Quiz


class QuizNotFound(Exception):
    """Quiz does not exist."""

    pass


class QuizAccessDenied(Exception):
    """User does not own the quiz."""

    pass


def get_user_owned_quiz(quiz_id, user):
    """Return a quiz only if it exists and belongs to the given user."""
    quiz = (
        Quiz.objects.prefetch_related("questions")
        .filter(id=quiz_id)
        .first()
    )
    if not quiz:
        raise QuizNotFound()
    if quiz.owner_id != user.id:
        raise QuizAccessDenied()
    return quiz


def quiz_error_response(exception):
    """Map known quiz exceptions to API responses."""
    if isinstance(exception, QuizNotFound):
        return Response(
            {"detail": "Quiz not found"},
            status=status.HTTP_404_NOT_FOUND,
        )
    if isinstance(exception, QuizAccessDenied):
        return Response(
            {"detail": "Access denied"},
            status=status.HTTP_403_FORBIDDEN,
        )
    return Response(
        {"detail": "Internal server error"},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def server_error_response():
    """Return a generic 500 internal server error response."""
    return Response(
        {"detail": "Internal server error"},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
