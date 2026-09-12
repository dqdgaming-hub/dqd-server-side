import json
import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

# Adjust this import to match wherever TermsAndConditions actually lives
# in your project (e.g. "core.models", "users.models", "accounts.models").
from ...models import TermsAndConditions


TERMS_DATA = {
    "title": "Terms & Conditions",
    "org": "DQD Gaming Hub",
    "version": "1.0",
    "effective_date": "2026-07-02",
    "intro": (
        "Welcome to DQD Gaming Hub. By entering our premises, booking a "
        "gaming station or pool table, or using our services, you agree "
        "to the following Terms & Conditions."
    ),
    "sections": [
        {
            "num": "01",
            "title": "General Conduct",
            "icon": "conduct",
            "bullets": [
                "All customers must behave respectfully towards staff, other customers, and gaming hub property.",
                "Any abusive language, harassment, threats, violence, or disruptive behavior is strictly prohibited.",
                "Management reserves the right to refuse service or ask any customer to leave the premises without a refund if these rules are violated.",
            ],
        },
        {
            "num": "02",
            "title": "Bookings & Payments",
            "icon": "payments",
            "bullets": [
                "All bookings are subject to availability.",
                "Payment must be completed before the session begins unless otherwise approved by management.",
                "Gaming and pool table sessions start at the scheduled booking time.",
                "Additional time will be charged according to the applicable rates and is subject to availability.",
            ],
        },
        {
            "num": "03",
            "title": "Gaming & Pool Equipment",
            "icon": "equipment",
            "paragraphs": [
                "Customers must use all gaming systems, consoles, PCs, accessories, pool tables, cues, and other equipment responsibly.",
            ],
            "bulletsIntro": "The following are strictly prohibited:",
            "bullets": [
                "Tampering with hardware or software.",
                "Installing unauthorized software or applications.",
                "Changing system settings.",
                "Misusing gaming or pool equipment.",
            ],
            "outro": [
                "Any customer who intentionally or negligently damages equipment, furniture, accessories, or any other gaming hub property will be responsible for the full cost of repair or replacement.",
            ],
        },
        {
            "num": "04",
            "title": "Outside Food & Beverages",
            "icon": "food",
            "paragraphs": [
                "Outside food and beverages are not permitted inside DQD Gaming Hub unless specifically approved by management.",
                "Food and drinks purchased from the hub must be consumed responsibly. Any damage caused by spills or negligence may result in cleaning or repair charges.",
            ],
        },
        {
            "num": "05",
            "title": "Illegal Activities",
            "icon": "illegal",
            "severity": "high",
            "paragraphs": [
                "DQD Gaming Hub maintains a zero-tolerance policy toward illegal activities.",
            ],
            "bulletsIntro": "The following are strictly prohibited:",
            "bullets": [
                "Gambling or betting for money where prohibited by law.",
                "Possession or use of illegal drugs or controlled substances.",
                "Smoking or vaping in prohibited areas.",
                "Carrying illegal weapons or dangerous items.",
                "Piracy, hacking, cheating software, unauthorized access to computer systems, or any cybercrime.",
                "Viewing, downloading, sharing, or distributing illegal, obscene, or prohibited content.",
                "Any activity that violates applicable local, state, or national laws.",
            ],
            "outro": [
                "Customers engaging in illegal activities may be removed immediately from the premises, have their access permanently banned, and may be reported to the appropriate law enforcement authorities where required.",
                "DQD Gaming Hub accepts no responsibility or liability for any illegal acts committed by customers while using our facilities.",
            ],
        },
        {
            "num": "06",
            "title": "Customer Responsibility",
            "icon": "responsibility",
            "bulletsIntro": "Customers are responsible for:",
            "bullets": [
                "Their own actions and conduct.",
                "The safety of their personal belongings.",
                "Logging out of all personal gaming accounts before leaving.",
            ],
            "outro": [
                "DQD Gaming Hub is not liable for the loss, theft, or damage of personal belongings left unattended.",
            ],
        },
        {
            "num": "07",
            "title": "Damage to Property",
            "icon": "damage",
            "paragraphs": [
                "Any damage caused to gaming systems, pool tables, furniture, décor, accessories, electrical equipment, or any other gaming hub property due to misuse, negligence, or intentional acts shall be the sole responsibility of the customer responsible. Management reserves the right to recover the full repair or replacement cost.",
            ],
        },
        {
            "num": "08",
            "title": "CCTV Surveillance",
            "icon": "cctv",
            "paragraphs": [
                "CCTV surveillance operates throughout the premises for the safety and security of customers, staff, and property.",
            ],
        },
        {
            "num": "09",
            "title": "Health & Safety",
            "icon": "safety",
            "paragraphs": [
                "Customers must follow all safety instructions provided by staff and must not engage in any behavior that could endanger themselves or others.",
            ],
        },
        {
            "num": "10",
            "title": "Limitation of Liability",
            "icon": "liability",
            "bulletsIntro": "DQD Gaming Hub shall not be responsible for:",
            "bullets": [
                "Loss or theft of personal belongings.",
                "Service interruptions due to power failures, internet outages, or technical issues beyond our control.",
                "Injuries or losses resulting from a customer's failure to follow safety instructions or these Terms & Conditions.",
                "Any illegal activities committed by customers on or off the premises.",
            ],
        },
        {
            "num": "11",
            "title": "Right to Refuse Service",
            "icon": "refuse",
            "bulletsIntro": "Management reserves the right to:",
            "bullets": [
                "Refuse entry or service to any person.",
                "Cancel bookings when necessary.",
                "Remove customers who violate these Terms & Conditions without refund.",
                "Recover costs for any damages caused to gaming hub property.",
            ],
        },
        {
            "num": "12",
            "title": "Changes to These Terms",
            "icon": "changes",
            "paragraphs": [
                "DQD Gaming Hub reserves the right to update these Terms & Conditions at any time. Continued use of our services constitutes acceptance of any revised Terms.",
            ],
        },
        {
            "num": "13",
            "title": "Contact Us",
            "icon": "contact",
            "paragraphs": [
                "For any questions regarding these Terms & Conditions, please contact DQD Gaming Hub through the contact details available on our website.",
            ],
        },
    ],
}


class Command(BaseCommand):
    help = "Seeds the default DQD Gaming Hub Terms & Conditions record."

    def add_arguments(self, parser):
        parser.add_argument(
            "--terms-version",
            dest="terms_version",
            default=TERMS_DATA["version"],
            help="Version string to seed/update (default: %(default)s).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        version = options["terms_version"]
        effective_date = datetime.date.fromisoformat(TERMS_DATA["effective_date"])

        obj, created = TermsAndConditions.objects.update_or_create(
            version=version,
            defaults={
                "title": TERMS_DATA["title"],
                "content": json.dumps(TERMS_DATA),
                "effective_date": effective_date,
                "is_current": True,
            },
        )

        # TermsAndConditions.save() already flips every other row's
        # is_current to False when is_current=True is set here, so no
        # extra cleanup is needed.

        verb = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} TermsAndConditions v{obj.version} "
                f"(id={obj.id}, effective_date={obj.effective_date}, is_current={obj.is_current})."
            )
        )

# run py manage.py seed_terms --version 1.0