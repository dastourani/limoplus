from django.db import migrations, models


class Migration(migrations.Migration):
    replaces = [
        ("website", "0013_teacherapplication_collaboration_scope_and_more"),
    ]

    dependencies = [
        ("website", "0012_sitesettings_coming_soon_note_and_more"),
    ]

    operations = [
        migrations.AddField(
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
        migrations.AddField(
            model_name="teacherapplication",
            name="resume_url",
            field=models.URLField(blank=True, default="", max_length=500, verbose_name="لینک صفحه معرفی یا رزومه"),
        ),
        migrations.AlterField(
            model_name="teacherapplication",
            name="book_or_link",
            field=models.CharField(max_length=300, verbose_name="رشته و عنوان کتاب یا درس پیشنهادی"),
        ),
        migrations.AlterField(
            model_name="teacherapplication",
            name="explanation",
            field=models.TextField(blank=True, default="", max_length=2000, verbose_name="توضیحات تکمیلی یا سابقه تدریس"),
        ),
        migrations.AlterField(
            model_name="teacherapplication",
            name="sample_work",
            field=models.TextField(blank=True, default="", max_length=3000, verbose_name="توضیح کوتاه نمونه\u200cکار یا شواهد"),
        ),
    ]
