import base64
import io
import mimetypes
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image


NONCE_SIZE = 12
AUTH_TAG_SIZE = 16
MAX_IMAGE_SIZE = 10 * 1024 * 1024

IMAGE_CONTENT_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
}


@dataclass(frozen=True)
class EncryptedImagePayload:
    encrypted_content: bytes
    filename: str
    content_type: str


def _get_encryption_key() -> bytes:
    key_value = getattr(settings, "IMAGE_ENCRYPTION_KEY", "")

    if not key_value:
        raise RuntimeError("IMAGE_ENCRYPTION_KEY is not configured.")

    if not isinstance(key_value, str):
        raise RuntimeError("IMAGE_ENCRYPTION_KEY must be a base64 string.")

    try:
        key = base64.urlsafe_b64decode(key_value.encode("ascii"))
    except Exception as exc:
        raise RuntimeError("IMAGE_ENCRYPTION_KEY is not valid base64.") from exc

    if len(key) != 32:
        raise RuntimeError("IMAGE_ENCRYPTION_KEY must decode to exactly 32 bytes.")

    return key


def _inspect_image(content: bytes) -> str:
    if not content:
        raise ValidationError("Image cannot be empty.")

    if len(content) > MAX_IMAGE_SIZE:
        raise ValidationError(
            f"Image size cannot exceed {MAX_IMAGE_SIZE // (1024 * 1024)} MB."
        )

    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()

        with Image.open(io.BytesIO(content)) as image:
            image_format = image.format
    except Exception as exc:
        raise ValidationError("Uploaded file is not a valid image.") from exc

    content_type = IMAGE_CONTENT_TYPES.get(image_format)

    if not content_type:
        raise ValidationError("This image format is not supported.")

    return content_type


def validate_image_bytes(content: bytes) -> None:
    _inspect_image(content)


def encrypt_image(content: bytes) -> bytes:
    if not isinstance(content, bytes):
        raise ValidationError("Image content must be binary data.")

    validate_image_bytes(content)

    key = _get_encryption_key()
    nonce = os.urandom(NONCE_SIZE)

    ciphertext = AESGCM(key).encrypt(
        nonce,
        content,
        None,
    )

    return nonce + ciphertext


def _coerce_encrypted_bytes(value) -> bytes:
    if value is None:
        return b""

    if isinstance(value, bytes):
        return value

    if isinstance(value, bytearray):
        return bytes(value)

    if isinstance(value, memoryview):
        return value.tobytes()

    raise ValidationError(
        "Image data is not stored as encrypted binary data. "
        "Re-upload the image or migrate the existing image."
    )


def decrypt_image(encrypted_content: bytes) -> bytes:
    encrypted_content = _coerce_encrypted_bytes(encrypted_content)

    if not encrypted_content:
        return b""

    if len(encrypted_content) < NONCE_SIZE + AUTH_TAG_SIZE:
        raise ValidationError("Invalid encrypted image data.")

    key = _get_encryption_key()
    nonce = encrypted_content[:NONCE_SIZE]
    ciphertext = encrypted_content[NONCE_SIZE:]

    try:
        return AESGCM(key).decrypt(
            nonce,
            ciphertext,
            None,
        )
    except InvalidTag as exc:
        raise ValidationError(
            "Unable to decrypt image. The encryption key or stored image data is invalid."
        ) from exc


def _default_filename(content_type: str) -> str:
    extension = mimetypes.guess_extension(content_type) or ".img"
    return f"image{extension}"


def encrypt_image_bytes(
    content: bytes,
    filename: str = "",
) -> EncryptedImagePayload:
    if not isinstance(content, bytes):
        try:
            content = bytes(content)
        except Exception as exc:
            raise ValidationError("Image content must be valid binary data.") from exc

    content_type = _inspect_image(content)

    filename = os.path.basename(filename or "").strip()

    if not filename:
        filename = _default_filename(content_type)

    return EncryptedImagePayload(
        encrypted_content=encrypt_image(content),
        filename=filename[:255],
        content_type=content_type,
    )


def encrypt_uploaded_image(uploaded_file) -> EncryptedImagePayload:
    if uploaded_file is None or not hasattr(uploaded_file, "read"):
        raise ValidationError("A valid image file is required.")

    declared_size = getattr(uploaded_file, "size", None)

    if declared_size is not None and declared_size > MAX_IMAGE_SIZE:
        raise ValidationError(
            f"Image size cannot exceed {MAX_IMAGE_SIZE // (1024 * 1024)} MB."
        )

    try:
        position = uploaded_file.tell()
    except (AttributeError, OSError):
        position = None

    try:
        content = uploaded_file.read()
    finally:
        if position is not None:
            try:
                uploaded_file.seek(position)
            except (AttributeError, OSError):
                pass

    if not isinstance(content, bytes):
        try:
            content = bytes(content)
        except Exception as exc:
            raise ValidationError("Uploaded image content is invalid.") from exc

    return encrypt_image_bytes(
        content=content,
        filename=getattr(uploaded_file, "name", ""),
    )


def image_to_data_uri(
    encrypted_content: bytes,
    content_type: str = "",
) -> str | None:
    if encrypted_content is None:
        return None

    decrypted = decrypt_image(encrypted_content)

    if not decrypted:
        return None

    detected_content_type = _inspect_image(decrypted)
    content_type = content_type.strip() if isinstance(content_type, str) else ""

    if not content_type:
        content_type = detected_content_type

    encoded = base64.b64encode(decrypted).decode("ascii")

    return f"data:{content_type};base64,{encoded}"


def safe_image_to_data_uri(
    encrypted_content,
    content_type: str = "",
) -> str | None:
    if encrypted_content is None:
        return None

    try:
        return image_to_data_uri(encrypted_content, content_type)
    except (ValidationError, ValueError, TypeError, RuntimeError):
        return None
