from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_user_email_verification_token_user_email_verified_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="panellogincode",
            name="staff_only",
            field=models.BooleanField(default=True),
        ),
    ]
