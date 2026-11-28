from django.db import migrations

GROUP_NAME = "استاد کتاب"
LABEL_PERMISSIONS = (
    ("catalog", "label", "view_label", "Can view برچسب متن"),
    ("catalog", "label", "add_label", "Can add برچسب متن"),
    ("catalog", "label", "change_label", "Can change برچسب متن"),
    ("catalog", "label", "delete_label", "Can delete برچسب متن"),
)

def add_label_permissions_to_teacher(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    alias = schema_editor.connection.alias

    group = Group.objects.using(alias).filter(name=GROUP_NAME).first()
    if not group:
        return
    for app_label, model, codename, name in LABEL_PERMISSIONS:
        content_type, _ = ContentType.objects.using(alias).get_or_create(app_label=app_label, model=model)
        permission, _ = Permission.objects.using(alias).get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )
        group.permissions.add(permission)

def remove_label_permissions_from_teacher(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    alias = schema_editor.connection.alias

    group = Group.objects.using(alias).filter(name=GROUP_NAME).first()
    if not group:
        return
    for _, _, codename, _ in LABEL_PERMISSIONS:
        perm = Permission.objects.using(alias).filter(codename=codename, content_type__app_label="catalog").first()
        if perm:
            group.permissions.remove(perm)

class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0032_label_created_by"),
    ]

    operations = [
        migrations.RunPython(add_label_permissions_to_teacher, remove_label_permissions_from_teacher),
    ]
