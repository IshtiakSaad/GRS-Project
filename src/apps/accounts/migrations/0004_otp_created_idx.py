from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False  # CONCURRENTLY: codes keep being issued while the index builds

    dependencies = [
        ("accounts", "0003_identity"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="otpchallenge",
            index=models.Index(fields=["created_at"], name="otp_created_idx"),
        ),
    ]
