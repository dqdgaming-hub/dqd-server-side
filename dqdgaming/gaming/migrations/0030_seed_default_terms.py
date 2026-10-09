import datetime
import json

from django.db import migrations

from gaming.management.commands.seed_terms import TERMS_DATA


def seed_default_terms(apps, schema_editor):
    TermsAndConditions = apps.get_model("gaming", "TermsAndConditions")
    terms = TermsAndConditions.objects.using(schema_editor.connection.alias)

    if terms.filter(
        is_current=True,
        is_active=True,
        is_deleted=False,
    ).exists():
        return

    terms.update(is_current=False)
    terms.update_or_create(
        version=TERMS_DATA["version"],
        defaults={
            "title": TERMS_DATA["title"],
            "content": json.dumps(TERMS_DATA),
            "effective_date": datetime.date.fromisoformat(
                TERMS_DATA["effective_date"]
            ),
            "is_current": True,
            "is_active": True,
            "is_deleted": False,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("gaming", "0029_alter_passwordresetotp_otp"),
    ]

    operations = [
        migrations.RunPython(
            seed_default_terms,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
