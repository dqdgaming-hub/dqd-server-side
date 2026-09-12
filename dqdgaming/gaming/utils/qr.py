import qrcode
from io import BytesIO
from django.core.files import File


def generate_qr_code(data: str, filename: str) -> File:
    """
    Generate a QR code image for `data` and return it
    as a Django File object ready to save to an ImageField.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return File(buffer, name=filename)
