from django.contrib import admin
from django.utils import timezone

from .models import Choice, ExamSource, Flashcard, Question, QuestionSource, Report


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 4
    max_num = 6


class QuestionSourceInline(admin.TabularInline):
    model = QuestionSource
    extra = 0
    autocomplete_fields = ("source",)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "node", "difficulty", "domain", "answer_count", "is_archived")
    list_filter = ("difficulty", "domain", "kind", "is_original", "is_free", "is_archived")
    search_fields = ("stem",)
    autocomplete_fields = ("flashcards",)
    raw_id_fields = ("node",)
    inlines = [ChoiceInline, QuestionSourceInline]
    readonly_fields = ("answer_count", "correct_count")


@admin.register(Flashcard)
class FlashcardAdmin(admin.ModelAdmin):
    list_display = ("title", "node", "is_free", "is_archived")
    search_fields = ("title", "point", "slug")
    raw_id_fields = ("node",)


@admin.register(ExamSource)
class ExamSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "group", "booklet")
    search_fields = ("name", "group")
    list_filter = ("year",)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "reason", "status", "question", "flashcard", "node")
    list_filter = ("status", "reason")
    search_fields = ("note", "user__phone")
    raw_id_fields = ("user", "question", "flashcard", "node")
    actions = ["mark_fixed", "mark_rejected"]

    @admin.action(description="علامت «اصلاح شد»")
    def mark_fixed(self, request, queryset):
        queryset.update(status=Report.Status.FIXED, resolved_at=timezone.now())

    @admin.action(description="علامت «بررسی شد، درست بود»")
    def mark_rejected(self, request, queryset):
        queryset.update(status=Report.Status.REJECTED, resolved_at=timezone.now())
