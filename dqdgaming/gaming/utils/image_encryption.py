import base64
import io
import mimetypes
import os
from dataclasses import dataclass
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image


# AES-GCM recommended nonce size.
NONCE_SIZE = 12

# AES-GCM authentication tag size.
AUTH_TAG_SIZE = 16

# Maximum uploaded file size.
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB

# Maximum decoded image pixels.
# This protects against decompression-bomb images.
MAX_IMAGE_PIXELS = 25_000_000


# Image formats supported by the application.
#
# Keep these formats limited to formats that your application/browser
# actually needs to display.
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


@lru_cache(maxsize=1)
def _decode_encryption_key(key_value: str) -> bytes:
    """
    Decode and validate the base64 encryption key.

    Cached so the environment variable is not base64-decoded for
    every image upload/download.
    """
    if not isinstance(key_value, str) or not key_value:
        raise RuntimeError(
            "IMAGE_ENCRYPTION_KEY must be configured as a base64 string."
        )

    try:
        # Support both padded and unpadded base64.
        padded_value = key_value + ("=" * (-len(key_value) % 4))
        key = base64.urlsafe_b64decode(padded_value.encode("ascii"))
    except (ValueError, UnicodeEncodeError, base64.binascii.Error) as exc:
        raise RuntimeError(
            "IMAGE_ENCRYPTION_KEY is not valid base64."
        ) from exc

    if len(key) != 32:
        raise RuntimeError(
            "IMAGE_ENCRYPTION_KEY must decode to exactly 32 bytes."
        )

    return key


def _get_encryption_key() -> bytes:
    key_value = getattr(settings, "IMAGE_ENCRYPTION_KEY", "")

    if not key_value:
        raise RuntimeError(
            "IMAGE_ENCRYPTION_KEY is not configured."
        )

    return _decode_encryption_key(key_value)


def _inspect_image(content: bytes) -> str:
    """
    Validate the image once and return the detected MIME type.

    This function intentionally performs only one Pillow inspection.
    """
    if not content:
        raise ValidationError("Image cannot be empty.")

    if len(content) > MAX_IMAGE_SIZE:
        raise ValidationError(
            f"Image size cannot exceed "
            f"{MAX_IMAGE_SIZE // (1024 * 1024)} MB."
        )

    try:
        with Image.open(io.BytesIO(content)) as image:
            image_format = image.format

            if not image_format:
                raise ValidationError(
                    "Unable to determine image format."
                )

            # Protect against very large decoded images.
            width, height = image.size

            if width <= 0 or height <= 0:
                raise ValidationError(
                    "Image dimensions are invalid."
                )

            if width * height > MAX_IMAGE_PIXELS:
                raise ValidationError(
                    "Image dimensions are too large."
                )

            # Verify the image structure once.
            #
            # This is much cheaper than loading/decompressing the complete
            # image and is enough for upload validation in this workflow.
            image.verify()

    except ValidationError:
        raise

    except Exception as exc:
        raise ValidationError(
            "Uploaded file is not a valid image."
        ) from exc

    content_type = IMAGE_CONTENT_TYPES.get(image_format.upper())

    if not content_type:
        raise ValidationError(
            f"Image format '{image_format}' is not supported."
        )

    return content_type


def validate_image_bytes(content: bytes) -> None:
    """
    Validate image bytes.
    """
    _inspect_image(content)


def _encrypt_bytes(content: bytes) -> bytes:
    """
    Encrypt already validated image bytes using AES-256-GCM.

    Stored format:

        [12-byte nonce][ciphertext + 16-byte GCM tag]
    """
    key = _get_encryption_key()
    nonce = os.urandom(NONCE_SIZE)

    ciphertext = AESGCM(key).encrypt(
        nonce,
        content,
        None,
    )

    return nonce + ciphertext


def encrypt_image(content: bytes) -> bytes:
    """
    Validate and encrypt an image.

    Image validation happens exactly once.
    """
    if not isinstance(content, bytes):
        raise ValidationError(
            "Image content must be binary data."
        )

    _inspect_image(content)

    return _encrypt_bytes(content)


def _coerce_bytes(value) -> bytes:
    """
    Convert supported binary values to bytes.
    """
    if value is None:
        return b""

    if isinstance(value, bytes):
        return value

    if isinstance(value, bytearray):
        return bytes(value)

    if isinstance(value, memoryview):
        return value.tobytes()

    raise ValidationError(
        "Image data must be stored as binary data."
    )


def _default_filename(content_type: str) -> str:
    extension = mimetypes.guess_extension(content_type)

    if not extension:
        extension = ".img"

    return f"image{extension}"


def _clean_filename(filename: str) -> str:
    """
    Keep only the filename component and remove path separators.
    """
    if not isinstance(filename, str):
        return ""

    filename = filename.replace("\\", "/")
    filename = os.path.basename(filename)
    filename = filename.strip()

    # Remove null bytes.
    filename = filename.replace("\x00", "")

    return filename[:255]


def encrypt_image_bytes(
    content: bytes,
    filename: str = "",
) -> EncryptedImagePayload:
    """
    Validate and encrypt raw image bytes.

    IMPORTANT:
    The image is inspected only once.
    """
    content = _coerce_bytes(content)

    if not content:
        raise ValidationError("Image cannot be empty.")

    # One validation only.
    content_type = _inspect_image(content)

    filename = _clean_filename(filename)

    if not filename:
        filename = _default_filename(content_type)

    encrypted_content = _encrypt_bytes(content)

    return EncryptedImagePayload(
        encrypted_content=encrypted_content,
        filename=filename,
        content_type=content_type,
    )


def encrypt_uploaded_image(uploaded_file) -> EncryptedImagePayload:
    """
    Encrypt a Django UploadedFile.

    Reads the file once and validates/encrypts it without running
    the Pillow validation twice.
    """
    if uploaded_file is None or not hasattr(uploaded_file, "read"):
        raise ValidationError(
            "A valid image file is required."
        )

    declared_size = getattr(uploaded_file, "size", None)

    if (
        declared_size is not None
        and declared_size > MAX_IMAGE_SIZE
    ):
        raise ValidationError(
            f"Image size cannot exceed "
            f"{MAX_IMAGE_SIZE // (1024 * 1024)} MB."
        )

    # Remember current position when possible.
    try:
        original_position = uploaded_file.tell()
    except (AttributeError, OSError):
        original_position = None

    try:
        content = uploaded_file.read()
    finally:
        # Restore original position when possible.
        if original_position is not None:
            try:
                uploaded_file.seek(original_position)
            except (AttributeError, OSError):
                pass

    if not isinstance(content, bytes):
        try:
            content = bytes(content)
        except Exception as exc:
            raise ValidationError(
                "Uploaded image content is invalid."
            ) from exc

    return encrypt_image_bytes(
        content=content,
        filename=getattr(uploaded_file, "name", ""),
    )


def decrypt_image(encrypted_content: bytes) -> bytes:
    """
    Decrypt AES-256-GCM image data.

    Expected format:

        [12-byte nonce][ciphertext + 16-byte authentication tag]
    """
    encrypted_content = _coerce_bytes(encrypted_content)

    if not encrypted_content:
        return b""

    if len(encrypted_content) < NONCE_SIZE + AUTH_TAG_SIZE:
        raise ValidationError(
            "Invalid encrypted image data."
        )

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
            "Unable to decrypt image. "
            "The encryption key or stored image data is invalid."
        ) from exc


def _validate_content_type(content_type: str) -> str:
    """
    Validate a stored/provided content type against the application
    allowlist.
    """
    if not isinstance(content_type, str):
        return ""

    content_type = content_type.strip().lower()

    allowed_types = set(
        IMAGE_CONTENT_TYPES.values()
    )

    if content_type not in allowed_types:
        return ""

    return content_type


def image_to_data_uri(
    encrypted_content: bytes,
    content_type: str = "",
) -> str | None:
    """
    Decrypt an image and return it as a base64 data URI.

    Performance optimization:
    If a valid content_type is already stored with the image,
    Pillow does NOT need to inspect the decrypted image again.
    """
    if encrypted_content is None:
        return None

    decrypted = decrypt_image(encrypted_content)

    if not decrypted:
        return None

    # Use the already-known MIME type whenever possible.
    content_type = _validate_content_type(content_type)

    # Only inspect the decrypted image if the content type was not supplied.
    if not content_type:
        content_type = _inspect_image(decrypted)

    encoded = base64.b64encode(decrypted).decode("ascii")

    return (
        f"data:{content_type};base64,{encoded}"
    )


def safe_image_to_data_uri(
    encrypted_content,
    content_type: str = "",
) -> str | None:
    """
    Safe wrapper for image_to_data_uri().
    """
    if encrypted_content is None:
        return None

    try:
        return image_to_data_uri(
            encrypted_content=encrypted_content,
            content_type=content_type,
        )

    except (
        ValidationError,
        ValueError,
        TypeError,
        RuntimeError,
    ):
        return None