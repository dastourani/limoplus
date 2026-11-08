from django.db import migrations


def forward(apps, schema_editor):
    """The «لاتین» box: English (or any left-to-right) text, left-aligned, with a «بیشتر:» part opened on a tap.
    A label of that name made in the panel already is left as it is."""
    Label = apps.get_model("catalog", "Label")
    order = (Label.objects.order_by("-order").values_list("order", flat=True).first() or 0) + 10
    Label.objects.get_or_create(
        name="لاتین",
        defaults={"group": "زبان", "style": "table", "numbered": False, "icon": "languages",
                  "aliases": "LTR، انگلیسی، English، چپ‌چین", "order": order},
    )


class Migration(migrations.Migration):

    dependencies = [("catalog", "0019_label_icons")]

    # Backwards keeps the label: labels are never deleted (books may use it).
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
