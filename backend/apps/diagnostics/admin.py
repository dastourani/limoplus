from __future__ import annotations

import json
from datetime import timedelta

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html

from apps.catalog.jalali import fa_digits, jalali_datetime
from apps.catalog.panel_display import fa_number

from .checks import run_all_health_checks
from .models import ErrorGroup, HealthCheckRun
from .service import build_ai_report


class SuperuserOnlyAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return bool(request.user and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)


class PlatformFilter(admin.SimpleListFilter):
    title = "بستر / پلتفرم"
    parameter_name = "platform"

    def lookups(self, request, model_admin):
        return (
            ("panel", "پنل استاد و مدیر"),
            ("website", "سایت"),
            ("web", "وب‌اپ"),
            ("android", "اپ اندروید"),
        )

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            return queryset.filter(events__platform=val).distinct()
        return queryset


@admin.register(ErrorGroup)
class ErrorGroupAdmin(SuperuserOnlyAdmin):
    list_display = (
        "title_col",
        "status_badge",
        "severity_badge",
        "source",
        "events_col",
        "installs_col",
        "users_col",
        "last_build",
        "last_seen_col",
    )
    list_filter = ("status", "severity", "source", PlatformFilter, "kind")
    search_fields = ("title", "code", "route", "first_build", "last_build", "events__event_id", "events__request_id")
    readonly_fields = (
        "fingerprint",
        "source",
        "kind",
        "code",
        "title",
        "route",
        "expected",
        "observed",
        "severity",
        "event_count",
        "install_count",
        "user_count",
        "first_build",
        "last_build",
        "first_seen_at",
        "last_seen_at",
        "resolved_at",
    )
    fields = (
        "status",
        "admin_note",
        "title",
        "code",
        "source",
        "kind",
        "severity",
        "route",
        "expected",
        "observed",
        "first_build",
        "last_build",
        "event_count",
        "install_count",
        "user_count",
        "first_seen_at",
        "last_seen_at",
        "resolved_at",
    )
    actions = ("mark_investigating", "mark_resolved", "mark_ignored", "mark_open")
    change_list_template = "admin/diagnostics/errorgroup/change_list.html"
    change_form_template = "admin/diagnostics/errorgroup/change_form.html"

    def has_change_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    def get_urls(self):
        site = self.admin_site.admin_view
        custom = [
            path("run-checks/", site(self.run_checks_view), name="diagnostics_errorgroup_run_checks"),
            path("<int:group_id>/set-status/", site(self.set_status_view), name="diagnostics_errorgroup_set_status"),
        ]
        return custom + super().get_urls()

    def run_checks_view(self, request):
        if request.method != "POST" or not request.user.is_superuser:
            raise PermissionDenied
        runs = run_all_health_checks()
        total_issues = sum(r.issues_found for r in runs if r.completed)
        failed = [r.get_check_key_display() for r in runs if not r.completed]
        if failed:
            messages.warning(request, f"بررسی سلامت اجرا شد اما این بخش‌ها خطا دادند: {'، '.join(failed)}")
        elif total_issues:
            messages.warning(request, f"بررسی سلامت انجام شد و {fa_number(total_issues)} مغایرت یافت شد.")
        else:
            messages.success(request, "بررسی سلامت با موفقیت انجام شد؛ مغایرت قطعی یافت نشد.")
        return redirect("admin:diagnostics_errorgroup_changelist")

    def set_status_view(self, request, group_id: int):
        if request.method != "POST" or not request.user.is_superuser:
            raise PermissionDenied
        group = get_object_or_404(ErrorGroup, pk=group_id)
        new_status = (request.POST.get("status") or "").strip()
        if new_status in ErrorGroup.Status.values:
            group.status = new_status
            group.resolved_at = timezone.now() if new_status == ErrorGroup.Status.RESOLVED else None
            group.save(update_fields=["status", "resolved_at"])
            messages.success(request, f"وضعیت به «{group.get_status_display()}» تغییر کرد.")
        return redirect("admin:diagnostics_errorgroup_change", group.pk)

    def changelist_view(self, request, extra_context=None):
        now = timezone.now()
        stale_cutoff = now - timedelta(hours=26)

        def _latest_card(key: str, label: str):
            run = HealthCheckRun.objects.filter(check_key=key, completed=True).order_by("-ran_at", "-id").first()
            failed_last = HealthCheckRun.objects.filter(check_key=key).order_by("-ran_at", "-id").first()
            return {
                "key": key,
                "label": label,
                "run": run,
                "at": jalali_datetime(run.ran_at) if run else None,
                "stale": bool(run is None or run.ran_at < stale_cutoff),
                "last_failed": bool(failed_last and not failed_last.completed),
                "summary": run.summary if run else "هنوز اجرا نشده است.",
                "issues": run.issues_found if run else 0,
                "pending": run.pending_count if run else 0,
                "details": run.details if run else {},
            }

        extra = {
            **(extra_context or {}),
            "open_count": fa_number(ErrorGroup.objects.filter(status__in=[ErrorGroup.Status.OPEN, ErrorGroup.Status.INVESTIGATING]).count()),
            "critical_open_count": fa_number(
                ErrorGroup.objects.filter(
                    status__in=[ErrorGroup.Status.OPEN, ErrorGroup.Status.INVESTIGATING],
                    severity=ErrorGroup.Severity.CRITICAL,
                ).count()
            ),
            "health_cards": [
                _latest_card(HealthCheckRun.CheckKey.PAYMENTS, "پرداخت و دسترسی"),
                _latest_card(HealthCheckRun.CheckKey.REVIEWS, "جلسه‌های مرور"),
                _latest_card(HealthCheckRun.CheckKey.OFFLINE, "بسته‌های آفلاین (۲۴ساعت)"),
            ],
        }
        return super().changelist_view(request, extra_context=extra)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_object(request, object_id)
        extra = dict(extra_context or {})
        if obj is not None:
            samples = []
            for ev in obj.events.order_by("-created_at", "-id")[:25]:
                samples.append({
                    "event_id": ev.event_id,
                    "at": jalali_datetime(ev.created_at),
                    "request_id": ev.request_id,
                    "op_id": ev.op_id,
                    "user_ref": ev.user_ref,
                    "install_short": ev.install_id[:12] if ev.install_id else "",
                    "platform": ev.platform,
                    "channel": ev.channel,
                    "app_build": ev.app_build,
                    "server_version": ev.server_version,
                    "version_mismatch": ev.version_mismatch,
                    "is_offline": ev.is_offline,
                    "route": ev.route,
                    "expected": ev.expected,
                    "observed": ev.observed,
                    "evidence_json": json.dumps(ev.evidence, ensure_ascii=False, indent=2) if ev.evidence else "",
                })
            extra["ai_report"] = build_ai_report(obj)
            extra["samples"] = samples
            extra["status_choices"] = ErrorGroup.Status.choices
        return super().change_view(request, object_id, form_url, extra_context=extra)

    @admin.display(description="عنوان و مسیر", ordering="title")
    def title_col(self, obj):
        if obj.route:
            return format_html(
                '<strong>{}</strong><div class="lp-quiet" style="direction:ltr;text-align:right">{}</div>',
                obj.title,
                obj.route,
            )
        return format_html("<strong>{}</strong>", obj.title)

    @admin.display(description="وضعیت", ordering="status")
    def status_badge(self, obj):
        cls = {
            ErrorGroup.Status.OPEN: "lp-b-red",
            ErrorGroup.Status.INVESTIGATING: "lp-b-yellow",
            ErrorGroup.Status.RESOLVED: "lp-b-green",
            ErrorGroup.Status.IGNORED: "lp-b-grey",
        }.get(obj.status, "lp-b-grey")
        return format_html('<span class="lp-badge {}">{}</span>', cls, obj.get_status_display())

    @admin.display(description="شدت", ordering="severity")
    def severity_badge(self, obj):
        cls = {
            ErrorGroup.Severity.CRITICAL: "lp-b-red",
            ErrorGroup.Severity.ERROR: "lp-b-yellow",
            ErrorGroup.Severity.WARNING: "lp-b-blue",
        }.get(obj.severity, "lp-b-grey")
        return format_html('<span class="lp-badge {}">{}</span>', cls, obj.get_severity_display())

    @admin.display(description="رخداد", ordering="event_count")
    def events_col(self, obj):
        return fa_number(obj.event_count)

    @admin.display(description="نصب", ordering="install_count")
    def installs_col(self, obj):
        return fa_number(obj.install_count)

    @admin.display(description="کاربر", ordering="user_count")
    def users_col(self, obj):
        return fa_number(obj.user_count)

    @admin.display(description="آخرین مشاهده", ordering="last_seen_at")
    def last_seen_col(self, obj):
        return fa_digits(jalali_datetime(obj.last_seen_at))

    @admin.action(description="علامت‌گذاری: در حال بررسی")
    def mark_investigating(self, request, queryset):
        queryset.update(status=ErrorGroup.Status.INVESTIGATING, resolved_at=None)

    @admin.action(description="علامت‌گذاری: برطرف شد")
    def mark_resolved(self, request, queryset):
        queryset.update(status=ErrorGroup.Status.RESOLVED, resolved_at=timezone.now())

    @admin.action(description="علامت‌گذاری: نادیده گرفته‌شده")
    def mark_ignored(self, request, queryset):
        queryset.update(status=ErrorGroup.Status.IGNORED)

    @admin.action(description="بازگشایی")
    def mark_open(self, request, queryset):
        queryset.update(status=ErrorGroup.Status.OPEN, resolved_at=None)


@admin.register(HealthCheckRun)
class HealthCheckRunAdmin(SuperuserOnlyAdmin):
    list_display = ("check_key", "completed_badge", "checked_col", "issues_col", "pending_col", "summary", "ran_at_col")
    list_filter = ("check_key", "completed")

    @admin.display(description="وضعیت اجرا", ordering="completed")
    def completed_badge(self, obj):
        return format_html(
            '<span class="lp-badge {}">{}</span>',
            "lp-b-green" if obj.completed else "lp-b-red",
            "موفق" if obj.completed else "ناموفق",
        )

    @admin.display(description="بررسی‌شده", ordering="checked_count")
    def checked_col(self, obj):
        return fa_number(obj.checked_count)

    @admin.display(description="مغایرت", ordering="issues_found")
    def issues_col(self, obj):
        return fa_number(obj.issues_found)

    @admin.display(description="در انتظار", ordering="pending_count")
    def pending_col(self, obj):
        return fa_number(obj.pending_count)

    @admin.display(description="زمان اجرا", ordering="ran_at")
    def ran_at_col(self, obj):
        return fa_digits(jalali_datetime(obj.ran_at))
