"""申报书分节正文表（前端 EditorView 9 节持久化）。"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("p", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PApplicationDoc",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("tenant_id", models.BigIntegerField()),
                ("section_code", models.CharField(max_length=64)),
                ("content_rich", models.TextField(blank=True, null=True)),
                ("word_count", models.IntegerField(default=0)),
                ("doc_version", models.IntegerField(default=1)),
                ("updated_by", models.BigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "application",
                    models.ForeignKey(
                        db_column="application_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        to="p.papplication",
                    ),
                ),
            ],
            options={
                "db_table": "p_application_doc",
                "unique_together": {("application", "section_code")},
            },
        ),
    ]
