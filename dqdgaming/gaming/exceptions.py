import logging

from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler


logger = logging.getLogger("gaming.errors")


def _first_message(data):
    """Pull one human readable message out of a DRF error payload."""
    if isinstance(data, str):
        return data
    if isinstance(data, list) and data:
        return _first_message(data[0])
    if isinstance(data, dict):
        for key in ("detail", "message", "non_field_errors"):
            if key in data:
                return _first_message(data[key])
        for value in data.values():
            message = _first_message(value)
            if message:
                return message
    return ""


def api_exception_handler(exc, context):
    """Consistent JSON errors; never leak stack traces or SQL to clients.

    Every error response carries ``detail`` (one readable sentence) so the
    frontend can always show ``err.response.data.detail``. Field errors are
    kept alongside it for forms.
    """
    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(getattr(exc, "message_dict", None) or exc.messages)

    response = exception_handler(exc, context)

    if response is None:
        view = context.get("view")
        request = context.get("request")
        if isinstance(exc, ObjectDoesNotExist):
            # e.g. a refresh token for an account that no longer exists
            if type(view).__name__.startswith("Token"):
                return Response(
                    {"detail": "Your session has expired. Please sign in again.", "code": "token_not_valid"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if isinstance(exc, IntegrityError):
            logger.warning("Integrity error in %s: %s", type(view).__name__, exc)
            return Response(
                {"detail": "This record conflicts with existing data. Please refresh and try again."},
                status=status.HTTP_409_CONFLICT,
            )
        logger.exception(
            "Unhandled error in %s %s (%s)",
            getattr(request, "method", "?"),
            getattr(request, "path", "?"),
            type(view).__name__,
            exc_info=exc,
        )
        message = (
            "The service is temporarily unavailable. Please try again."
            if isinstance(exc, DatabaseError)
            else "Something went wrong. Please try again."
        )
        return Response({"detail": message}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    data = response.data
    if isinstance(data, dict) and isinstance(data.get("detail"), list):
        data["detail"] = _first_message(data["detail"])
    if isinstance(data, list):
        response.data = {"detail": _first_message(data) or "Invalid request.", "errors": data}
    elif isinstance(data, dict) and "detail" not in data:
        response.data = {"detail": _first_message(data) or "Invalid request.", **data}

    return response
