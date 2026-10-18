"""Production settings for the dqdgaming Django project."""

import json
import os
from datetime import timedelta
from pathlib import Path

from corsheaders.defaults import default_headers as default_cors_headers
from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


# ============================================================
# ENVIRONMENT HELPERS
# ============================================================

def env(name, default=None, *, required=False):
    """Read an environment variable and fail early for required settings."""
    value = os.getenv(name, default)

    if required and not value:
        raise ImproperlyConfigured(f"{name} must be set.")

    return value


def env_bool(name, default=False):
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    try:
        return int(env(name, str(default)))
    except (TypeError, ValueError) as error:
        raise ImproperlyConfigured(
            f"{name} must be an integer."
        ) from error


def env_list(name, default=""):
    value = env(name, default)

    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]


# ============================================================
# CORE DJANGO SETTINGS
# ============================================================

DEBUG = env_bool(
    "DJANGO_DEBUG",
    default=False,
)

SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    required=True,
)

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
)

if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS must contain your production hostnames."
    )


INSTALLED_APPS = [
    "corsheaders",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "gaming",
]


MIDDLEWARE = [
    "gaming.middleware.RequestLogMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "gaming.middleware.UpdateLastSeenMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
]


ROOT_URLCONF = "dqdgaming.urls"
WSGI_APPLICATION = "dqdgaming.wsgi.application"
ASGI_APPLICATION = "dqdgaming.asgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "gaming.CustomUser"


TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# ============================================================
# DATABASE
# ============================================================

DB_ENGINE = env(
    "DB_ENGINE",
    "django.db.backends.postgresql",
)

if DB_ENGINE == "django.db.backends.sqlite3":
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": env(
                "DB_NAME",
                str(BASE_DIR / "db.sqlite3"),
            ),
        }
    }
else:
    database_options = {}

    db_sslmode = env(
        "DB_SSLMODE",
        "",
    )

    if db_sslmode:
        database_options["sslmode"] = db_sslmode

    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": env("DB_NAME", required=True),
            "USER": env("DB_USER", required=True),
            "PASSWORD": env("DB_PASSWORD", required=True),
            "HOST": env("DB_HOST", required=True),
            "PORT": env("DB_PORT", "5432"),
            "CONN_MAX_AGE": env_int(
                "DB_CONN_MAX_AGE",
                60,
            ),
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": database_options,
        }
    }


# ============================================================
# CACHE
# ============================================================

# Throttling, login lockout for unknown accounts and OTP limits use the
# cache. With more than one gunicorn worker or server behind a load
# balancer set REDIS_URL so every process shares the same counters.
REDIS_URL = env("REDIS_URL", "")

if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "TIMEOUT": env_int("DJANGO_CACHE_TIMEOUT", 300),
            "KEY_PREFIX": "dqd",
            "OPTIONS": {
                "socket_connect_timeout": 2,
                "socket_timeout": 2,
                "retry_on_timeout": True,
            },
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "dqdgaming-cache",
            "TIMEOUT": env_int(
                "DJANGO_CACHE_TIMEOUT",
                300,
            ),
        }
    }


# ============================================================
# PASSWORD VALIDATION
# ============================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# ============================================================
# INTERNATIONALIZATION
# ============================================================

LANGUAGE_CODE = "en-us"

TIME_ZONE = env(
    "DJANGO_TIME_ZONE",
    "Asia/Kolkata",
)

USE_I18N = True
USE_TZ = True


# ============================================================
# STATIC / MEDIA
#
# BinaryField-encrypted images do not use MEDIA_ROOT for storage,
# but these settings may still be needed by other application code.
# ============================================================

# Request size limits (also limit at the reverse proxy).
DATA_UPLOAD_MAX_MEMORY_SIZE = env_int("DATA_UPLOAD_MAX_MEMORY_SIZE", 10 * 1024 * 1024)
FILE_UPLOAD_MAX_MEMORY_SIZE = env_int("FILE_UPLOAD_MAX_MEMORY_SIZE", 5 * 1024 * 1024)
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ============================================================
# DJANGO REST FRAMEWORK
# ============================================================

REST_FRAMEWORK = {
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # JWT + refreshes the device's last-seen time and IP
        "gaming.authentication.TrackedJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "EXCEPTION_HANDLER": "gaming.exceptions.api_exception_handler",
    # Throttles key on client IP; 0 = REMOTE_ADDR (ignore spoofable X-Forwarded-For).
    "NUM_PROXIES": env_int("NUM_PROXIES", 1) if env_bool("USE_X_FORWARDED_FOR", default=not DEBUG) else 0,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env(
            "DRF_ANON_THROTTLE",
            "100/hour",
        ),
        "public_home": env(
            "DRF_HOME_THROTTLE",
            "1000/hour",
        ),
        "user": env(
            "DRF_USER_THROTTLE",
            "1000/hour",
        ),
        "login": env(
            "DRF_LOGIN_THROTTLE",
            "10/minute",
        ),
        "register": env(
            "DRF_REGISTER_THROTTLE",
            "5/hour",
        ),
        "password_reset": env(
            "DRF_PASSWORD_RESET_THROTTLE",
            "20/hour",
        ),
        "social_login": env(
            "DRF_SOCIAL_LOGIN_THROTTLE",
            "10/minute",
        ),
        "booking": env(
            "DRF_BOOKING_THROTTLE",
            "30/hour",
        ),
    },
}


# ============================================================
# JWT
# ============================================================

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=env_int(
            "JWT_ACCESS_MINUTES",
            30,
        )
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=env_int(
            "JWT_REFRESH_DAYS",
            7,
        )
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "SIGNING_KEY": env(
        "JWT_SIGNING_KEY",
        required=True,
    ),
    "ISSUER": env(
        "JWT_ISSUER",
        required=True,
    ),
    "AUTH_HEADER_TYPES": ("Bearer",),
}


# ============================================================
# SOCIAL LOGIN
# ============================================================

GOOGLE_CLIENT_ID = env(
    "GOOGLE_CLIENT_ID",
    "",
)
GOOGLE_CLIENT_SECRET = env(
    "GOOGLE_CLIENT_SECRET",
    "",
)

FACEBOOK_APP_ID = env(
    "FACEBOOK_APP_ID",
    "",
)

FACEBOOK_APP_SECRET = env(
    "FACEBOOK_APP_SECRET",
    "",
)


# ============================================================
# EMAIL
# ============================================================

EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend",
)

EMAIL_HOST = env(
    "EMAIL_HOST",
    "",
)

EMAIL_PORT = env_int(
    "EMAIL_PORT",
    587,
)

EMAIL_HOST_USER = env(
    "EMAIL_HOST_USER",
    "",
)

EMAIL_HOST_PASSWORD = env(
    "EMAIL_HOST_PASSWORD",
    "",
)

EMAIL_USE_TLS = env_bool(
    "EMAIL_USE_TLS",
    default=True,
)

EMAIL_TIMEOUT = env_int(
    "EMAIL_TIMEOUT",
    10,
)

DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL",
    required=True,
)

SERVER_EMAIL = env(
    "SERVER_EMAIL",
    DEFAULT_FROM_EMAIL,
)


# ============================================================
# APPLICATION URLS
# ============================================================

SITE_URL = env(
    "SITE_URL",
    required=True,
).rstrip("/")

# May be a comma separated list; the first entry is used in emails / links.
FRONTEND_URLS = [url.rstrip("/") for url in env_list("FRONTEND_URL")]

if not FRONTEND_URLS:
    raise ImproperlyConfigured("FRONTEND_URL must be set.")

FRONTEND_URL = FRONTEND_URLS[0]


# ============================================================
# LOGIN / PASSWORD RESET LIMITS
# ============================================================

LOGIN_MAX_ATTEMPTS = env_int("LOGIN_MAX_ATTEMPTS", 3)
LOGIN_LOCKOUT_MINUTES = env_int("LOGIN_LOCKOUT_MINUTES", 15)

PASSWORD_RESET_MAX_RESENDS = env_int("PASSWORD_RESET_MAX_RESENDS", 3)
PASSWORD_RESET_WINDOW_HOURS = env_int("PASSWORD_RESET_WINDOW_HOURS", 24)
PASSWORD_RESET_RESEND_COOLDOWN_SECONDS = env_int(
    "PASSWORD_RESET_RESEND_COOLDOWN_SECONDS",
    60,
)


# ============================================================
# PHONE / WHATSAPP
# ============================================================

# Prefixed to 10-digit local numbers so logins and wa.me links match.
DEFAULT_PHONE_COUNTRY_CODE = env("DEFAULT_PHONE_COUNTRY_CODE", "91")
LOCAL_PHONE_LENGTH = env_int("LOCAL_PHONE_LENGTH", 10)

# Business WhatsApp number users message after booking (digits only).
WHATSAPP_SENDER_NUMBER = env("WHATSAPP_SENDER_NUMBER", "")
WHATSAPP_BUSINESS_NAME = env("VENUE_NAME", "DQD Gaming")
VENUE_ADDRESS = env("VENUE_ADDRESS", "")
VENUE_PHONE = env("VENUE_PHONE", "")

SLOW_REQUEST_MS = env_int("SLOW_REQUEST_MS", 1000)


# ============================================================
# BOOKING RULES (one flow for games, combos, events, points)
# ============================================================

BOOKING_OPEN_HOUR = env_int("BOOKING_OPEN_HOUR", 10)
BOOKING_CLOSE_HOUR = env_int("BOOKING_CLOSE_HOUR", 22)
BOOKING_MAX_HOURS = env_int("BOOKING_MAX_HOURS", 6)
BOOKING_MAX_DAYS_AHEAD = env_int("BOOKING_MAX_DAYS_AHEAD", 60)
LOYALTY_POINTS_PER_HOUR = env_int("LOYALTY_POINTS_PER_HOUR", 100)


# ============================================================
# CORS / CSRF
# ============================================================

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
)

CORS_ALLOW_HEADERS = (
    *default_cors_headers,
    "x-device-id",
    "x-client-info",
    "x-request-id",
)

CORS_EXPOSE_HEADERS = ["X-Request-ID"]

CORS_ALLOW_CREDENTIALS = env_bool(
    "CORS_ALLOW_CREDENTIALS",
    default=False,
)

CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
)


# ============================================================
# GOOGLE SHEETS
#
# Preferred production setup:
#   GOOGLE_SHEET_CREDENTIALS=/path/to/service-account.json
#
# Optional alternative:
#   GOOGLE_SERVICE_ACCOUNT_JSON={...}
#
# At least one must be configured.
# ============================================================

GOOGLE_SHEET_CREDENTIALS = env(
    "GOOGLE_SHEET_CREDENTIALS",
    "",
)

GOOGLE_SERVICE_ACCOUNT_JSON = env(
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "",
)

GOOGLE_SERVICE_ACCOUNT_INFO = None
GOOGLE_SHEET_CREDENTIALS_PATH = None

if GOOGLE_SHEET_CREDENTIALS:
    GOOGLE_SHEET_CREDENTIALS_PATH = (
        BASE_DIR / GOOGLE_SHEET_CREDENTIALS
    )

    if not GOOGLE_SHEET_CREDENTIALS_PATH.exists():
        raise ImproperlyConfigured(
            "Google credentials file not found: "
            f"{GOOGLE_SHEET_CREDENTIALS_PATH}"
        )

if GOOGLE_SERVICE_ACCOUNT_JSON:
    try:
        GOOGLE_SERVICE_ACCOUNT_INFO = json.loads(
            GOOGLE_SERVICE_ACCOUNT_JSON
        )
    except json.JSONDecodeError as error:
        raise ImproperlyConfigured(
            "GOOGLE_SERVICE_ACCOUNT_JSON contains invalid JSON."
        ) from error

if not GOOGLE_SHEET_CREDENTIALS and not GOOGLE_SERVICE_ACCOUNT_JSON:
    raise ImproperlyConfigured(
        "Configure either GOOGLE_SHEET_CREDENTIALS "
        "or GOOGLE_SERVICE_ACCOUNT_JSON."
    )

GOOGLE_SHEET_ID = env(
    "GOOGLE_SHEET_ID",
    required=True,
)


# ============================================================
# IMAGE ENCRYPTION
#
# Must decode to exactly 32 bytes for AES-256-GCM.
# ============================================================

IMAGE_ENCRYPTION_KEY = env(
    "IMAGE_ENCRYPTION_KEY",
    required=True,
)


# ============================================================
# DEVICE ACTIVITY
# ============================================================

USE_X_FORWARDED_FOR = env_bool(
    "USE_X_FORWARDED_FOR",
    default=not DEBUG,
)

# Client IP behind proxies: count NUM_PROXIES entries from the right of
# X-Forwarded-For (the left part is client supplied and can be forged).
NUM_PROXIES_FOR_IP = env_int("NUM_PROXIES", 1)

# Use nginx's X-Real-IP instead (only if the proxy always overwrites it).
TRUST_X_REAL_IP = env_bool("TRUST_X_REAL_IP", default=False)

DEVICE_ACTIVITY_INTERVAL_SECONDS = env_int(
    "DEVICE_ACTIVITY_INTERVAL_SECONDS",
    120,
)


# ============================================================
# SECURITY
# ============================================================

SECURE_SSL_REDIRECT = env_bool(
    "SECURE_SSL_REDIRECT",
    default=not DEBUG,
)

if env_bool(
    "USE_X_FORWARDED_PROTO",
    default=False,
):
    SECURE_PROXY_SSL_HEADER = (
        "HTTP_X_FORWARDED_PROTO",
        "https",
    )

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

SESSION_COOKIE_HTTPONLY = True

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

X_FRAME_OPTIONS = "DENY"


if not DEBUG and SECURE_SSL_REDIRECT:
    SECURE_HSTS_SECONDS = env_int(
        "DJANGO_HSTS_SECONDS",
        31_536_000,
    )

    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
        "DJANGO_HSTS_INCLUDE_SUBDOMAINS",
        default=False,
    )

    SECURE_HSTS_PRELOAD = env_bool(
        "DJANGO_HSTS_PRELOAD",
        default=False,
    )


# ============================================================
# CONTENT SECURITY POLICY
# ============================================================

CSP_POLICY = {
    "default-src": [CSP.SELF],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
    "object-src": [CSP.NONE],
    "img-src": [
        CSP.SELF,
        "data:",
        "https:",
    ],
}


if env_bool(
    "DJANGO_CSP_ENFORCE",
    default=False,
):
    SECURE_CSP = CSP_POLICY
else:
    SECURE_CSP_REPORT_ONLY = CSP_POLICY


# ============================================================
# LOGGING
# ============================================================

LOG_LEVEL = env(
    "DJANGO_LOG_LEVEL",
    "INFO",
).upper()


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": (
                "{asctime} {levelname} "
                "{name} {message}"
            ),
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "gaming.requests": {
            "handlers": ["console"],
            "level": env("REQUEST_LOG_LEVEL", "INFO").upper(),
            "propagate": False,
        },
    },
}
