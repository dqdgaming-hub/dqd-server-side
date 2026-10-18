"""Store user phones as international digits so mobile login and WhatsApp work.

Rows that cannot be normalized, or that would collide with another user's
number, are left unchanged (and logged) rather than failing the deploy.
"""

import logging

from django.db import migrations


logger = logging.getLogger(__name__)


def normalize_phones(apps, schema_editor):
    from gaming.utils.phone import InvalidPhone, normalize_phone

    CustomUser = apps.get_model("gaming", "CustomUser")

    taken = set(
        CustomUser.objects.exclude(phone__isnull=True).values_list("phone", flat=True)
    )

    for user in CustomUser.objects.exclude(phone__isnull=True).only("id", "phone", "email"):
        raw = user.phone
        if not raw or not raw.strip():
            CustomUser.objects.filter(pk=user.pk).update(phone=None)
            continue
        try:
            normalized = normalize_phone(raw)
        except InvalidPhone:
            logger.warning("Leaving unparseable phone for user %s unchanged.", user.pk)
            continue
        if normalized == raw:
            continue
        if normalized in taken:
            logger.warning("Phone for user %s would duplicate another user; unchanged.", user.pk)
            continue
        CustomUser.objects.filter(pk=user.pk).update(phone=normalized)
        taken.discard(raw)
        taken.add(normalized)

    # Empty-string emails would break the (now nullable) unique constraint.
    CustomUser.objects.filter(email="").update(email=None)


class Migration(migrations.Migration):

    dependencies = [
        ("gaming", "0031_security_lockout_indexes"),
    ]

    operations = [
        migrations.RunPython(normalize_phones, migrations.RunPython.noop),
    ]
