"""Login lockout and password-reset OTP resend limits.

Lockout state lives on the user row so it is shared by every worker /
server behind the load balancer. Unknown identifiers are tracked in the
cache only so their responses look identical (no account enumeration).
"""

import hashlib
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone


def max_login_attempts():
    return max(int(getattr(settings, "LOGIN_MAX_ATTEMPTS", 3)), 1)


def lockout_duration():
    return timedelta(minutes=int(getattr(settings, "LOGIN_LOCKOUT_MINUTES", 15)))


def _cache_key(prefix, identifier):
    digest = hashlib.sha256(str(identifier).strip().lower().encode()).hexdigest()
    return f"{prefix}:{digest}"


class LoginLocked(Exception):
    def __init__(self, retry_after_seconds):
        self.retry_after_seconds = max(int(retry_after_seconds), 1)
        minutes = (self.retry_after_seconds + 59) // 60
        super().__init__(
            "Too many failed attempts. Your account is locked for "
            f"{minutes} minute{'s' if minutes != 1 else ''}. "
            "Try again later or reset your password."
        )


def check_not_locked(user, identifier):
    """Raise ``LoginLocked`` if the user (or unknown identifier) is locked."""
    now = timezone.now()
    if user is not None:
        if user.locked_until and user.locked_until > now:
            raise LoginLocked((user.locked_until - now).total_seconds())
        return

    locked_until = cache.get(_cache_key("login-lock", identifier))
    if locked_until and locked_until > now:
        raise LoginLocked((locked_until - now).total_seconds())


def register_failure(user, identifier):
    """Record a wrong password. Returns attempts left (0 = now locked)."""
    limit = max_login_attempts()
    now = timezone.now()

    if user is not None:
        # Atomic increment: concurrent wrong guesses cannot slip past the limit.
        type(user).objects.filter(pk=user.pk).update(
            failed_login_attempts=F("failed_login_attempts") + 1
        )
        user.refresh_from_db(fields=["failed_login_attempts", "locked_until"])
        attempts = user.failed_login_attempts
        if attempts >= limit:
            type(user).objects.filter(pk=user.pk).update(
                failed_login_attempts=0,
                locked_until=now + lockout_duration(),
            )
            raise LoginLocked(lockout_duration().total_seconds())
        return limit - attempts

    key = _cache_key("login-fail", identifier)
    ttl = int(lockout_duration().total_seconds())
    cache.add(key, 0, ttl)
    try:
        attempts = cache.incr(key)
    except ValueError:
        cache.set(key, 1, ttl)
        attempts = 1
    if attempts >= limit:
        cache.delete(key)
        cache.set(_cache_key("login-lock", identifier), now + lockout_duration(), ttl)
        raise LoginLocked(lockout_duration().total_seconds())
    return limit - attempts


def reset_failures(user):
    if user.failed_login_attempts or user.locked_until:
        type(user).objects.filter(pk=user.pk).update(
            failed_login_attempts=0,
            locked_until=None,
        )
        user.failed_login_attempts = 0
        user.locked_until = None


# ── Password reset OTP resend limit ─────────────────────────────


def otp_max_sends():
    # First code + PASSWORD_RESET_MAX_RESENDS resends.
    return 1 + max(int(getattr(settings, "PASSWORD_RESET_MAX_RESENDS", 3)), 0)


def otp_window():
    return timedelta(hours=int(getattr(settings, "PASSWORD_RESET_WINDOW_HOURS", 24)))


def otp_cooldown_seconds():
    return int(getattr(settings, "PASSWORD_RESET_RESEND_COOLDOWN_SECONDS", 60))


class OTPLimitReached(Exception):
    def __init__(self, message, retry_after_seconds):
        self.retry_after_seconds = max(int(retry_after_seconds), 1)
        super().__init__(message)


def check_otp_send_allowed(user, email):
    """Raise ``OTPLimitReached`` when no more codes may be sent.

    Returns the number of resends still available *after* this send.
    """
    from gaming.models import PasswordResetOTP

    now = timezone.now()
    window_start = now - otp_window()
    max_sends = otp_max_sends()

    if user is not None:
        sent = list(
            PasswordResetOTP.objects.filter(user=user, created_at__gte=window_start)
            .order_by("-created_at")
            .values_list("created_at", flat=True)[:max_sends]
        )
    else:
        sent = cache.get(_cache_key("otp-sent", email)) or []
        sent = [ts for ts in sent if ts >= window_start]

    if sent:
        wait = otp_cooldown_seconds() - (now - max(sent)).total_seconds()
        if wait > 0:
            raise OTPLimitReached(
                f"Please wait {int(wait) + 1} seconds before requesting a new code.",
                wait,
            )

    if len(sent) >= max_sends:
        retry_after = (min(sent) + otp_window() - now).total_seconds()
        raise OTPLimitReached(
            "You have reached the maximum of "
            f"{max_sends - 1} code resends. Please try again later.",
            retry_after,
        )

    if user is None:
        cache.set(
            _cache_key("otp-sent", email),
            [*sent, now],
            int(otp_window().total_seconds()),
        )

    return max_sends - len(sent) - 1
