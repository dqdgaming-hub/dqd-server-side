import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or promote a user to superuser/admin"

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
            user.is_superuser = True
            user.is_staff = True
            user.is_active = True
            user.is_verified = True
            user.role = "admin"
            user.set_password(password)

            user.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"User {email} promoted to superuser/admin successfully."
                )
            )
            return

        user = User(
            email=email,
            first_name="Admin",
            is_staff=True,
            is_superuser=True,
            is_active=True,
            is_verified=True,
            role="admin",
        )

        user.set_password(password)
        user.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Superuser/admin {email} created successfully."
            )
        )