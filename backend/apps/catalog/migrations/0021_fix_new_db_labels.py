from django.db import migrations

# On a brand-new database, 0014 already creates these labels from the live default list (without an icon), so the
# get_or_create in 0018 and 0020 finds them and sets nothing. Fill in what those migrations meant, only on rows that
# still have no icon (an icon chosen in the panel is never touched).
FIXES = {
    "تمرین": {"icon": "pen-line", "numbered": True},
    "پرسش و پاسخ": {"icon": "message-circle-question-mark"},
    "لاتین": {"icon": "languages"},
}


def fill(apps, schema_editor):
    Label = apps.get_model("catalog", "Label")
    for name, values in FIXES.items():
        Label.objects.filter(name=name, icon="").update(**values)


class Migration(migrations.Migration):
    dependencies = [("catalog", "0020_label_latin")]
    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
