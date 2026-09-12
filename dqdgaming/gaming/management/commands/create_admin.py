import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create superuser if it does not exist"

    def handle(self, *args, **options):
        User = get_user_model()

        email = os.environ.get("DJANGO_SUPERUSER_EMAIL")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

        if not email or not password:
            self.stdout.write(
                self.style.ERROR(
                    "DJANGO_SUPERUSER_EMAIL and DJANGO_SUPERUSER_PASSWORD "
                    "must be configured."
                )
            )
            return

        email = email.strip().lower()

        user = User.objects.filter(email=email).first()

        if user:
            if not user.is_superuser or not user.is_staff:
                user.is_superuser = True
                user.is_staff = True
                user.is_active = True
                user.set_password(password)
                user.save(
                    update_fields=[
                        "is_superuser",
                        "is_staff",
                        "is_active",
                        "password",
                    ]
                )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Existing user {email} has been promoted to superuser."
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Superuser {email} already exists."
                    )
                )

            return

        user = User(
            email=email,
            is_staff=True,
            is_superuser=True,
            is_active=True,
        )

        user.set_password(password)
        user.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Superuser {email} created successfully."
            )
        )
