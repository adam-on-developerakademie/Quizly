from django.urls import path

from .views import QuizCreateView


urlpatterns = [
	path("quizzes/", QuizCreateView.as_view(), name="quiz-create"),
]
