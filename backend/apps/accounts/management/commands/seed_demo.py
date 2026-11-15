from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, User
from apps.rooms.models import Room, RoomType, Tariff

# Placeholder inventory and prices. Replace with the college's real list (PRD open question).
ROOM_TYPES = [
    (
        "Standard Single",
        "A quiet single room with an attached bath.",
        1,
        ["Wi-Fi", "Attached bath", "Desk"],
        800,
        "1",
        6,
    ),
    (
        "Deluxe Double",
        "A larger air-conditioned room for two.",
        2,
        ["Wi-Fi", "AC", "Attached bath", "TV"],
        1500,
        "2",
        4,
    ),
    (
        "Family Suite",
        "Two rooms with a sitting area, for families.",
        4,
        ["Wi-Fi", "AC", "Sitting area", "Fridge"],
        2800,
        "3",
        2,
    ),
]
USERS = [
    ("admin", "IT Cell Admin", Role.ADMIN, "IT Cell"),
    ("manager", "Guesthouse Manager", Role.MANAGER, "Guesthouse Office"),
    ("registrar", "Registrar", Role.APPROVER, "Administration"),
    ("faculty", "Dr. Asha Rao", Role.REQUESTER, "Computer Science"),
]


class Command(BaseCommand):
    help = "Creates demo room types, rooms, prices and one user per staff role. For local development."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Run even when DEBUG is off.")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError("Refusing to seed demo data with DEBUG off. Pass --force if you mean it.")
        domain = settings.COLLEGE_EMAIL_DOMAINS[0]
        for local, name, role, department in USERS:
            email = f"{local}@{domain}"
            if not User.objects.filter(email=email).exists():
                User.objects.create_user(email=email, name=name, role=role, department=department)
            self.stdout.write(f"  {role:<10} {email}")
        for name, description, capacity, amenities, price, floor, count in ROOM_TYPES:
            room_type, created = RoomType.objects.get_or_create(
                name=name, defaults={"description": description, "capacity": capacity, "amenities": amenities}
            )
            if created:
                Tariff.objects.create(room_type=room_type, price_per_night=price, valid_from=date(2026, 1, 1))
                for n in range(1, count + 1):
                    Room.objects.create(number=f"{floor}{n:02d}", room_type=room_type, floor=int(floor))
        self.stdout.write(
            self.style.SUCCESS("Demo data ready. Sign in with any address above; the code is emailed (console in dev).")
        )
