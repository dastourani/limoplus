from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

GROUP_NAME = "استاد کتاب"
AI_PERMISSIONS = (
    ("catalog", "aiprovider", "view_aiprovider", "Can view ارائه‌دهنده هوش مصنوعی"),
    ("catalog", "aiprovider", "add_aiprovider", "Can add ارائه‌دهنده هوش مصنوعی"),
    ("catalog", "aiprovider", "change_aiprovider", "Can change ارائه‌دهنده هوش مصنوعی"),
    ("catalog", "aiprovider", "delete_aiprovider", "Can delete ارائه‌دهنده هوش مصنوعی"),
    ("catalog", "bookassistantauditlog", "view_bookassistantauditlog", "Can view لاگ ممیزی دستیار آموزشی"),
)

def add_permissions_to_teacher(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    alias = schema_editor.connection.alias

    group = Group.objects.using(alias).filter(name=GROUP_NAME).first()
    if not group:
        return
    for app_label, model, codename, name in AI_PERMISSIONS:
        content_type, _ = ContentType.objects.using(alias).get_or_create(app_label=app_label, model=model)
        permission, _ = Permission.objects.using(alias).get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )
        group.permissions.add(permission)

def remove_permissions_from_teacher(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    alias = schema_editor.connection.alias

    group = Group.objects.using(alias).filter(name=GROUP_NAME).first()
    if not group:
        return
    for _, _, codename, _ in AI_PERMISSIONS:
        perm = Permission.objects.using(alias).filter(codename=codename, content_type__app_label="catalog").first()
        if perm:
            group.permissions.remove(perm)

class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("catalog", "0038_aiprovider"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiprovider",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                help_text="اگر خالی باشد، این مدل سراسری/عمومی بوده و توسط مدیر کل تعریف شده است.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="ai_providers",
                to=settings.AUTH_USER_MODEL,
                verbose_name="استاد / مالک کلید",
            ),
        ),
        migrations.RunPython(add_permissions_to_teacher, remove_permissions_from_teacher),
    ]
