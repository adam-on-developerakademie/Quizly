"""URL routes for quiz API endpoints."""

from django.urls import path

from .views import QuizCreateView, QuizDetailView


urlpatterns = [
    path("quizzes/", QuizCreateView.as_view(), name="quiz-create"),
    path("quizzes/<int:id>/", QuizDetailView.as_view(), name="quiz-detail"),
]
