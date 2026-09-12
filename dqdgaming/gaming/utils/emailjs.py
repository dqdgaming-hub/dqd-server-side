import os
import requests
import logging

logger = logging.getLogger(__name__)

EMAILJS_API_URL = "https://api.emailjs.com/api/v1.0/email/send"


def send_emailjs(template_params, template_key="EMAILJS_TEMPLATE_ID"):

    payload = {
        "service_id": os.getenv("EMAILJS_SERVICE_ID"),
        "template_id": os.getenv(template_key),
        "user_id": os.getenv("EMAILJS_PUBLIC_KEY"),
        "accessToken": os.getenv("EMAILJS_PRIVATE_KEY"),
        "template_params": template_params,
    }

    try:
        response = requests.post(
            EMAILJS_API_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
            },
            timeout=30,
        )

        print("EMAILJS STATUS:", response.status_code)
        print("EMAILJS RESPONSE:", response.text)

        response.raise_for_status()

        return True

    except Exception as exc:
        logger.exception(exc)
        return False


def send_game_booking_email(booking, request):
    """
    Build template_params for template 2 and fire the email.
    Call this both on admin-create AND on approve.
    """
    extra_members_lines = []
    for idx, m in enumerate(booking.members.all(), start=2):
        extra_members_lines.append(
            f"{idx}. {m.name}{' · ' + m.phone if m.phone else ''}"
        )

    extra_members_str = "\n".join(extra_members_lines) if extra_members_lines else ""
    member_count = 1 + booking.members.count()  # primary + extras

    qr_url = ""
    if booking.qr_code:
        qr_url = request.build_absolute_uri(booking.qr_code.url)

    currency = lambda v: f"INR {float(v):.2f}" if v is not None else "—"
    print("QR URL:", qr_url)
    template_params = {
        "customer_name": booking.customer_name,
        "booking_id": booking.booking_id,
        "item_name": booking.item.name if booking.item else "—",
        "combo_name": booking.combo_pack.name if booking.combo_pack else "",
        "booking_date": str(booking.booking_date),
        "start_time": str(booking.start_time),
        "end_time": str(booking.end_time),
        "total_hours": str(booking.total_hours),
        "happy_hour": "⚡ Yes" if booking.is_happy_hour else "No",
        "member_count": str(member_count),
        "extra_members": extra_members_str,
        "subtotal": currency(booking.subtotal),
        "discount_amount": (
            currency(booking.discount_amount) if booking.discount_amount else "—"
        ),
        "total_amount": currency(booking.total_amount),
        "amount_paid": currency(booking.price_paid),
        "payment_status": booking.payment_status.upper(),
        "loyalty_points": str(
                booking.awarded_loyalty_points
                if booking.awarded_loyalty_points is not None
                else 10
            ),
        "qr_code_url": qr_url,
        "qr_token": str(booking.qr_token),
        "to_email": booking.customer_email,
    }

    return send_emailjs(template_params, template_key="EMAILJS_TEMPLATE_ID2")
