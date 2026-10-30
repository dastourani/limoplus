from django.contrib import admin
from treebeard.admin import TreeAdmin
from treebeard.forms import movenodeform_factory

from .models import Banner, ContentNode, Major


@admin.register(Major)
class MajorAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_coming_soon", "order")
    list_editable = ("is_coming_soon", "order")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ContentNode)
class ContentNodeAdmin(TreeAdmin):
    form = movenodeform_factory(ContentNode)
    list_display = ("title", "kind", "is_free", "is_published", "is_archived")
    list_filter = ("kind", "is_published", "is_free", "majors")
    search_fields = ("title",)
    filter_horizontal = ("majors",)


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("title", "is_active", "priority", "starts_at", "ends_at", "impressions", "clicks")
    list_editable = ("is_active", "priority")
    list_filter = ("is_active", "majors")
    filter_horizontal = ("majors",)
