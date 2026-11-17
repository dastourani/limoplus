from django.db import migrations, models

OLD_TAGLINE = "کتاب درسی‌ات را مثل یک لیمو بخور، برش به برش 🍋"
NEW_TAGLINE = "منبع درسی‌ات را برش‌به‌برش بخوان، مرور کن و مسلط شو 🍋"
OLD_INTRO = (
    "هر کتاب در لیموخوان یک خلاصه، یک درسنامه‌ی کامل، تست با پاسخ تشریحی و فلش‌کارت دارد. هر روز کمی بخوان؛ "
    "لیموخوان یادت می‌اندازد چه چیزی را دوباره مرور کنی."
)
NEW_INTRO = (
    "در لیموخوان هر کتاب یک درسنامه‌ی ساختارمند، چکیده‌ی مرور سریع، بانک تست کنکور با پاسخ تشریحی و فلش‌کارت‌های "
    "زمان‌بندی‌شده دارد؛ با برنامه‌ی مرور هوشمند که فراموشی را به صفر می‌رساند."
)
OLD_AUDIENCE = "برای کنکور ارشد، دکتری و امتحان‌های دانشگاه"
NEW_AUDIENCE = "ویژه‌ی داوطلبان کنکور ارشد، دکتری و امتحانات دانشگاهی"


def upgrade_defaults(apps, schema_editor):
    SiteSettings = apps.get_model("website", "SiteSettings")
    for row in SiteSettings.objects.all():
        changed = []
        if row.tagline == OLD_TAGLINE:
            row.tagline = NEW_TAGLINE
            changed.append("tagline")
        if row.intro == OLD_INTRO:
            row.intro = NEW_INTRO
            changed.append("intro")
        if row.audience == OLD_AUDIENCE:
            row.audience = NEW_AUDIENCE
            changed.append("audience")
        if changed:
            row.save(update_fields=changed)


def restore_defaults(apps, schema_editor):
    SiteSettings = apps.get_model("website", "SiteSettings")
    for row in SiteSettings.objects.all():
        changed = []
        if row.tagline == NEW_TAGLINE:
            row.tagline = OLD_TAGLINE
            changed.append("tagline")
        if row.intro == NEW_INTRO:
            row.intro = OLD_INTRO
            changed.append("intro")
        if row.audience == NEW_AUDIENCE:
            row.audience = OLD_AUDIENCE
            changed.append("audience")
        if changed:
            row.save(update_fields=changed)


class Migration(migrations.Migration):

    dependencies = [
        ("website", "0003_app_pages"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="features_title",
            field=models.CharField(default="یک منبع، چهار ابزار مکمل یادگیری", max_length=120, verbose_name="عنوان بخش چهار ویژگی"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="features_sub",
            field=models.CharField(default="تمام ابزارهای مطالعه و مرور، یکپارچه و منطبق با سرفصل‌های کتاب", max_length=200, verbose_name="زیرعنوان بخش ویژگی‌ها"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="feat1_title",
            field=models.CharField(default="درسنامه و چکیده‌ی دوحالته", max_length=80, verbose_name="عنوان باکس ۱"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="feat1_body",
            field=models.TextField(default="متن کامل درسی با کادرهای تعریف، فرمول، مثال و نکات کنکوری؛ به‌همراه چکیده‌ی یک‌صفحه‌ای برای مرور شب امتحان.", verbose_name="متن باکس ۱"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="feat2_title",
            field=models.CharField(default="بانک تست و دفترچه‌ی اشتباهات", max_length=80, verbose_name="عنوان باکس ۲"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="feat2_body",
            field=models.TextField(default="تست‌های طبقه‌بندی‌شده‌ی کنکور با پاسخ تشریحی گام‌به‌گام؛ تست‌های غلط یا شک‌دار خودکار وارد چرخه‌ی مرور می‌شوند.", verbose_name="متن باکس ۲"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="feat3_title",
            field=models.CharField(default="فلش‌کارت و واژه‌نامه‌ی لایتنر", max_length=80, verbose_name="عنوان باکس ۳"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="feat3_body",
            field=models.TextField(default="نکات کلیدی، فرمول‌ها و لغات تخصصی در ۶ جعبه‌ی مرور هوشمند (فردا، هفته‌ی بعد، ماه بعد) تا انتقال به حافظه‌ی بلندمدت.", verbose_name="متن باکس ۳"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="feat4_title",
            field=models.CharField(default="آمار پیشرفت و آزمون زمان‌دار", max_length=80, verbose_name="عنوان باکس ۴"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="feat4_body",
            field=models.TextField(default="لیموی پیشرفت هر فصل، سنجش آمادگی برای کنکورهای سال قبل و شبیه‌ساز آزمون با نمره‌ی منفی.", verbose_name="متن باکس ۴"),
        ),
        migrations.AlterField(
            model_name="sitesettings",
            name="tagline",
            field=models.CharField(default="منبع درسی‌ات را برش‌به‌برش بخوان، مرور کن و مسلط شو 🍋", max_length=120, verbose_name="جمله‌ی اصلی"),
        ),
        migrations.AlterField(
            model_name="sitesettings",
            name="intro",
            field=models.TextField(
                default="در لیموخوان هر کتاب یک درسنامه‌ی ساختارمند، چکیده‌ی مرور سریع، بانک تست کنکور با پاسخ تشریحی و فلش‌کارت‌های زمان‌بندی‌شده دارد؛ با برنامه‌ی مرور هوشمند که فراموشی را به صفر می‌رساند.",
                verbose_name="معرفی کوتاه",
            ),
        ),
        migrations.AlterField(
            model_name="sitesettings",
            name="audience",
            field=models.CharField(default="ویژه‌ی داوطلبان کنکور ارشد، دکتری و امتحانات دانشگاهی", max_length=120, verbose_name="برای چه کسانی"),
        ),
        migrations.RunPython(upgrade_defaults, restore_defaults),
    ]
