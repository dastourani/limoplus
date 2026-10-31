from django.contrib import admin
from django.template.response import TemplateResponse
from django.urls import path
from treebeard.admin import TreeAdmin
from treebeard.forms import movenodeform_factory

from .importer import import_file
from .models import Banner, ContentNode, Major

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


@admin.register(Major)
class MajorAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_coming_soon", "order")
    list_editable = ("is_coming_soon", "order")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ContentNode)
class ContentNodeAdmin(TreeAdmin):
    form = movenodeform_factory(ContentNode)
    change_list_template = "admin/catalog/contentnode/change_list.html"
    list_display = ("title", "kind", "slug", "is_free", "is_published", "is_archived")
    list_filter = ("kind", "is_published", "is_free", "is_archived", "majors")
    search_fields = ("title", "slug")
    filter_horizontal = ("majors",)
    actions = ["publish", "unpublish"]

    def get_urls(self):
        custom = [path("import/", self.admin_site.admin_view(self.import_view), name="catalog_contentnode_import")]
        return custom + super().get_urls()

    def import_view(self, request):
        if not self.has_add_permission(request):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        report = None
        if request.method == "POST" and request.FILES.get("file"):
            upload = request.FILES["file"]
            dry_run = request.POST.get("action") != "بارگذاری"
            if upload.size > MAX_UPLOAD_BYTES:
                report = {"filename": upload.name, "errors": ["حجم فایل بیشتر از ۵۰ مگابایت است."], "warnings": []}
            else:
                chapter, result = import_file(upload.name, upload.read(), publish=bool(request.POST.get("publish")), dry_run=dry_run)
                report = {
                    "filename": upload.name,
                    "errors": [str(i) for i in chapter.errors],
                    "warnings": [str(i) for i in chapter.warnings],
                    "summary": result.summary() if result else "",
                }
        context = {**self.admin_site.each_context(request), "title": "بارگذاری فصل از فایل", "report": report, "opts": self.model._meta}
        return TemplateResponse(request, "admin/catalog/contentnode/import.html", context)

    @admin.action(description="انتشار موارد انتخاب‌شده")
    def publish(self, request, queryset):
        queryset.update(is_published=True)

    @admin.action(description="خارج کردن از انتشار")
    def unpublish(self, request, queryset):
        queryset.update(is_published=False)


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("title", "target", "is_active", "priority", "starts_at", "ends_at", "impressions", "clicks")
    fields = ("title", "subtitle", "image", "target", "target_value", "link", "majors", "starts_at", "ends_at", "priority", "is_active")
    list_editable = ("is_active", "priority")
    list_filter = ("is_active", "majors")
    filter_horizontal = ("majors",)
