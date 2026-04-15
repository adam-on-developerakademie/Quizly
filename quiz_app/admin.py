"""Django admin configuration for quiz and question management."""

from django.contrib import admin

from .models import Question, Quiz


class QuestionInline(admin.TabularInline):
	"""Inline question editor shown on the quiz admin detail page."""

	model = Question
	extra = 0
	fields = ("question_title", "answer", "created_at", "updated_at")
	readonly_fields = ("created_at", "updated_at")
	show_change_link = True


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
	"""Admin configuration for viewing and managing quizzes."""

	list_display = (
		"id",
		"title",
		"owner",
		"youtube_video_id",
		"ai_status",
		"created_at",
		"updated_at",
	)
	list_filter = ("ai_status", "transcript_language", "created_at", "updated_at")
	search_fields = ("title", "description", "video_url", "youtube_video_id", "owner__username")
	readonly_fields = ("created_at", "updated_at")
	list_select_related = ("owner",)
	inlines = [QuestionInline]
	fieldsets = (
		("Basis", {"fields": ("owner", "title", "description", "video_url")}),
		(
			"YouTube-Metadaten",
			{"fields": ("youtube_video_id", "youtube_channel", "youtube_duration_seconds")},
		),
		("Audio", {"fields": ("audio_file", "audio_filename", "audio_filesize_bytes")}),
		(
			"Transkript",
			{"fields": ("transcript_language", "transcript_model", "transcript_text", "transcript_segments")},
		),
		(
			"AI-Generierung",
			{"fields": ("ai_generation_model", "ai_status", "ai_error_message", "ai_response_text", "ai_response_json")},
		),
		("Zeitstempel", {"fields": ("created_at", "updated_at")}),
	)

	def get_queryset(self, request):
		"""Limit queryset to owned quizzes for non-superusers."""
		queryset = super().get_queryset(request)
		if request.user.is_superuser:
			return queryset
		return queryset.filter(owner=request.user)

	def get_readonly_fields(self, request, obj=None):
		"""Prevent non-superusers from changing the quiz owner field."""
		readonly_fields = list(super().get_readonly_fields(request, obj))
		if not request.user.is_superuser:
			readonly_fields.append("owner")
		return readonly_fields

	def save_model(self, request, obj, form, change):
		"""Assign the current user as owner when creating a quiz in admin."""
		if not request.user.is_superuser and not obj.owner_id:
			obj.owner = request.user
		super().save_model(request, obj, form, change)

	def has_view_permission(self, request, obj=None):
		"""Allow viewing only own quiz objects for non-superusers."""
		if not super().has_view_permission(request, obj):
			return False
		if obj is None or request.user.is_superuser:
			return True
		return obj.owner_id == request.user.id

	def has_change_permission(self, request, obj=None):
		"""Allow editing only own quiz objects for non-superusers."""
		if not super().has_change_permission(request, obj):
			return False
		if obj is None or request.user.is_superuser:
			return True
		return obj.owner_id == request.user.id

	def has_delete_permission(self, request, obj=None):
		"""Allow deleting only own quiz objects for non-superusers."""
		if not super().has_delete_permission(request, obj):
			return False
		if obj is None or request.user.is_superuser:
			return True
		return obj.owner_id == request.user.id


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
	"""Admin configuration for viewing and managing quiz questions."""

	list_display = ("id", "question_title", "quiz", "answer", "created_at")
	list_filter = ("created_at", "updated_at")
	search_fields = ("question_title", "answer", "quiz__title")
	readonly_fields = ("created_at", "updated_at")
	list_select_related = ("quiz",)

	def get_queryset(self, request):
		"""Limit queryset to questions belonging to owned quizzes."""
		queryset = super().get_queryset(request)
		if request.user.is_superuser:
			return queryset
		return queryset.filter(quiz__owner=request.user)

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		"""Restrict quiz choices to owned quizzes for non-superusers."""
		if db_field.name == "quiz" and not request.user.is_superuser:
			kwargs["queryset"] = Quiz.objects.filter(owner=request.user)
		return super().formfield_for_foreignkey(db_field, request, **kwargs)

	def has_view_permission(self, request, obj=None):
		"""Allow viewing only own question objects for non-superusers."""
		if not super().has_view_permission(request, obj):
			return False
		if obj is None or request.user.is_superuser:
			return True
		return obj.quiz.owner_id == request.user.id

	def has_change_permission(self, request, obj=None):
		"""Allow editing only own question objects for non-superusers."""
		if not super().has_change_permission(request, obj):
			return False
		if obj is None or request.user.is_superuser:
			return True
		return obj.quiz.owner_id == request.user.id

	def has_delete_permission(self, request, obj=None):
		"""Allow deleting only own question objects for non-superusers."""
		if not super().has_delete_permission(request, obj):
			return False
		if obj is None or request.user.is_superuser:
			return True
		return obj.quiz.owner_id == request.user.id
