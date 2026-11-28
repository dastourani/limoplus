from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("website", "0014_teacherapplication_optional_collaboration_scope"),
    ]

    operations = [
        migrations.AlterField(
            model_name="teacherapplication",
            name="collaboration_scope",
            field=models.CharField(
                blank=True,
                choices=[
                    ("public_and_class", "عرضه در ویترین لیموخوان و کلاس\u200cهای اختصاصی"),
                    ("class_only", "استفاده در کلاس اختصاصی دانشجویان خودم (رایگان)"),
                    ("public_only", "عرضهٔ عمومی در ویترین لیموخوان"),
                ],
                default="",
                max_length=20,
                verbose_name="نحوه استفاده پیشنهادی",
            ),
        ),
    ]
