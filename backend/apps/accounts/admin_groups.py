"""Only the site manager may create or change groups: a group can grant panel and book access."""

from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import Group


try:
    admin.site.unregister(Group)
except NotRegistered:
    pass


@admin.register(Group)
class ManagerOnlyGroupAdmin(BaseGroupAdmin):
    """Groups are manager-only; the reserved teacher role is also immutable and least-privilege."""

    @staticmethod
    def _reserved_teacher_group(obj):
        return bool(obj and obj.name == "استاد کتاب")

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_add_permission(self, request):
        return bool(request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_superuser and not self._reserved_teacher_group(obj))

    def has_delete_permission(self, request, obj=None):
        return bool(request.user.is_superuser and not self._reserved_teacher_group(obj))
