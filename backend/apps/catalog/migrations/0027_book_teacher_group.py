from django.db import migrations


GROUP_NAME = "استاد کتاب"

# Deliberately limited: teachers draft assigned books and read their scoped lists. They do not get book metadata,
# publishing, user/group, student-access, or account-management permissions.
PERMISSIONS = (
    ("catalog", "book", "view_book", "Can view book"),
    ("catalog", "contentnode", "view_contentnode", "Can view content"),
    ("catalog", "contentnode", "change_contentnode", "Can change content"),
    ("catalog", "section", "view_section", "Can view section"),
    ("catalog", "chapterrevision", "view_chapterrevision", "Can view chapter revision"),
    ("learning", "question", "view_question", "Can view question"),
    ("learning", "flashcard", "view_flashcard", "Can view flashcard"),
    ("learning", "examsource", "view_examsource", "Can view exam source"),
    ("learning", "report", "view_report", "Can view report"),
    ("learning", "report", "change_report", "Can change report"),
)


def create_book_teacher_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    alias = schema_editor.connection.alias

    group, _ = Group.objects.using(alias).get_or_create(name=GROUP_NAME)
    permissions = []
    for app_label, model, codename, name in PERMISSIONS:
        content_type, _ = ContentType.objects.using(alias).get_or_create(app_label=app_label, model=model)
        permission, _ = Permission.objects.using(alias).get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )
        permissions.append(permission)
    # A pre-existing group with this reserved name may carry wider legacy permissions. Replace them so
    # the role remains least-privilege instead of merely adding the intended permissions on top.
    group.permissions.set(permissions)


def leave_group_in_place(apps, schema_editor):
    # A rollback must not silently remove a manually approved user's role.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("catalog", "0026_bookeditor"),
        ("learning", "0014_report_quote"),
    ]

    operations = [
        migrations.RunPython(create_book_teacher_group, leave_group_in_place),
    ]
