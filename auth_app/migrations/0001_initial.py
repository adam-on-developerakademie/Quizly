"""Initial migration for revoked token persistence."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Create the RevokedToken model."""

    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="RevokedToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("jti", models.CharField(db_index=True, max_length=255, unique=True)),
                ("token_type", models.CharField(max_length=32)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(auto_now_add=True)),
                ("source_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="auth.user")),
            ],
        ),
    ]
