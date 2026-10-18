from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import unquote

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from gaming.models import (
    Booking, ComboPack, CustomUser, EventBooking, ExclusiveEvent, GameCategory, GamingItem,
)

PASSWORD = "Str0ng-Pass!9"
DAY = (date.today() + timedelta(days=3)).isoformat()


def user(phone="919876543210", **extra):
    return CustomUser.objects.create_user(password=PASSWORD, first_name="Asha", phone=phone, **extra)


@override_settings(BOOKING_OPEN_HOUR=10, BOOKING_CLOSE_HOUR=22, BOOKING_MAX_HOURS=6, LOYALTY_POINTS_PER_HOUR=100,
                   WHATSAPP_SENDER_NUMBER="919000000000")
@patch.dict("rest_framework.settings.api_settings.__dict__", {"DEFAULT_THROTTLE_CLASSES": []})
class UnifiedBookingFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        category = GameCategory.objects.create(name="PS5", category_type="ps5")
        self.ps5 = GamingItem.objects.create(category=category, name="PS5 #1", price_per_hour=Decimal("200"),
                                             min_capacity=1, max_capacity=4)
        self.combo = ComboPack.objects.create(name="Duo Pack", snack_name="Popcorn", combo_price=Decimal("499"),
                                              loyalty_bonus=20, max_people=2)
        self.combo.gaming_items.add(self.ps5)
        self.event = ExclusiveEvent.objects.create(
            title="FIFA Night", description="Cup", event_date=date.today() + timedelta(days=5),
            start_time=time(18), end_time=time(21), price=Decimal("100"), max_participants=3,
        )
        self.me = user()
        self.client = APIClient()
        self.client.force_authenticate(self.me)

    def book(self, kind, target, **body):
        payload = {"kind": kind, "id": str(target.pk), **body}
        return self.client.post("/api/auth/user/book/", payload, format="json")

    def test_options_and_slots_are_uniform(self):
        for kind, target in (("game", self.ps5), ("combo", self.combo), ("event", self.event), ("loyalty", self.ps5)):
            res = self.client.get("/api/auth/user/book/options/", {"kind": kind, "id": str(target.pk)})
            self.assertEqual(res.status_code, 200, kind)
            self.assertIn("max_people", res.data)
        slots = self.client.get("/api/auth/user/book/slots/", {"kind": "game", "id": str(self.ps5.pk), "date": DAY})
        self.assertEqual(len(slots.data["slots"]), 12)
        self.assertTrue(all(s["available"] for s in slots.data["slots"]))

    def test_game_booking_with_members_and_price(self):
        res = self.book("game", self.ps5, date=DAY, start_time="14:00", hours=2,
                        members=[{"name": "Ravi", "phone": "98765 11111"}])
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["booking"]["total_amount"], "400.00")
        self.assertEqual(res.data["booking"]["people"], 2)
        self.assertNotIn("whatsapp_url", res.data)  # no user→venue message any more
        booking = Booking.objects.get(booking_id=res.data["booking"]["booking_id"])
        self.assertEqual(booking.members.get().phone, "919876511111")

    def test_combo_blocks_its_games_and_vice_versa(self):
        self.assertEqual(self.book("combo", self.combo, date=DAY, start_time="15:00", hours=1).status_code, 201)
        clash = self.book("game", self.ps5, date=DAY, start_time="15:00", hours=1)
        self.assertEqual(clash.status_code, 400)
        self.assertIn("just booked", clash.data["detail"])
        slots = self.client.get("/api/auth/user/book/slots/", {"kind": "game", "id": str(self.ps5.pk), "date": DAY})
        self.assertFalse(next(s for s in slots.data["slots"] if s["start_time"] == "15:00")["available"])

    def test_combo_capacity(self):
        res = self.book("combo", self.combo, date=DAY, start_time="11:00", hours=1,
                        members=[{"name": "A"}, {"name": "B"}])
        self.assertEqual(res.status_code, 400)
        self.assertIn("Only 2", res.data["detail"])

    def test_event_with_guests_uses_seats(self):
        res = self.book("event", self.event, members=[{"name": "Ravi"}])
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["booking"]["total_amount"], "200.00")
        self.assertEqual(self.event.available_slots, 1)
        other = APIClient()
        other.force_authenticate(user("919000000002"))
        full = other.post("/api/auth/user/book/", {"kind": "event", "id": str(self.event.pk),
                                                   "members": [{"name": "X"}]}, format="json")
        self.assertEqual(full.status_code, 400)

    def test_loyalty_points_booking(self):
        CustomUser.objects.filter(pk=self.me.pk).update(loyalty_points=250)
        res = self.book("loyalty", self.ps5, date=DAY, start_time="12:00", hours=2)
        self.assertEqual(res.status_code, 201, res.data)
        self.me.refresh_from_db()
        self.assertEqual(self.me.loyalty_points, 50)
        too_many = self.book("loyalty", self.ps5, date=DAY, start_time="16:00", hours=1)
        self.assertEqual(too_many.status_code, 400)

    def test_rejects_past_and_after_closing(self):
        self.assertEqual(self.book("game", self.ps5, date="2020-01-01", start_time="12:00").status_code, 400)
        late = self.book("game", self.ps5, date=DAY, start_time="21:00", hours=2)
        self.assertEqual(late.status_code, 400)
        self.assertIn("close", late.data["detail"])

    def test_admin_approval_message_is_detailed(self):
        res = self.book("game", self.ps5, date=DAY, start_time="14:00", hours=1, members=[{"name": "Ravi"}])
        booking = Booking.objects.get(booking_id=res.data["booking"]["booking_id"])
        admin = APIClient()
        admin.force_authenticate(CustomUser.objects.create_superuser(email="a@x.test", password=PASSWORD, first_name="A"))
        approved = admin.post(f"/api/auth/admin/bookings/{booking.pk}/approve/")
        text = unquote(approved.data["whatsapp_url"])
        for expected in ("confirmed", booking.booking_id, "PS5 #1", "2. Ravi", "Duration", "+91 90000 00000"):
            self.assertIn(expected, text)
        cancelled = admin.post(f"/api/auth/admin/bookings/{booking.pk}/reject/")
        self.assertNotIn("whatsapp_url", cancelled.data)
