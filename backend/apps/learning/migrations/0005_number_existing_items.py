from django.db import migrations


def number_items(apps, schema_editor):
    """Keep today's order (by id within each section) for items that already exist."""
    for name in ("Question", "Flashcard"):
        model = apps.get_model("learning", name)
        last_node, n = None, 0
        for item in model.objects.order_by("node_id", "id").only("id", "node_id"):
            if item.node_id != last_node:
                last_node, n = item.node_id, 0
            n += 1
            model.objects.filter(pk=item.pk).update(order=n)


class Migration(migrations.Migration):
    dependencies = [("learning", "0004_flashcard_order_question_order")]

    operations = [migrations.RunPython(number_items, migrations.RunPython.noop)]
