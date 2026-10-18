# DQD Gaming production deployment

## Files

1. Copy `settings.py` to `dqdgaming/settings.py`.
2. Copy `.env` to the project root, replace every `example.com` and `REPLACE...` value, and restrict its permissions to the deployment account.
3. Commit `.env.example`, but never commit `.env` or the Google service-account JSON.
4. Install the packages in `requirements-production.txt` alongside the existing project requirements.

Add this to `.gitignore`:

```gitignore
.env
.env.*
!.env.example
credentials/*.json
staticfiles/
media/
```

## Before opening traffic

```bash
python manage.py check --deploy
python manage.py migrate
python manage.py collectstatic --noinput
```

The migrations seed the default Terms & Conditions record when no active current
version exists, so the public `/api/auth/terms/` endpoint is ready before signup.

## Google sign-in

Set `GOOGLE_CLIENT_SECRET` in the backend `.env` to the secret for the same OAuth web client configured by `GOOGLE_CLIENT_ID` and `VITE_GOOGLE_CLIENT_ID`. Register each frontend sign-in URL (for example, `https://dqdgaming.com/sign-in` and `http://localhost:5173/sign-in`) as an authorized redirect URI in Google Cloud Console. Keep the client secret server-side; do not add it to a `VITE_` variable.

Run the application through a production WSGI server, for example:

```bash
gunicorn dqdgaming.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 60
```

Place Nginx, Caddy, or your cloud load balancer in front of the application. Terminate TLS there and serve `/static/` directly from `STATIC_ROOT`; serve `/media/` only if this single-server filesystem storage is intentional. For multiple application instances, move media to object storage.

Production defaults to trusting `X-Forwarded-For` for client IP tracking and to trusting `X-Forwarded-Proto` only when explicitly enabled. Keep this deployment behind a proxy that removes incoming forwarded headers and sets trusted values. For local development, `DEBUG=True` keeps IP tracking on `REMOTE_ADDR`.

```dotenv
USE_X_FORWARDED_PROTO=True
```

Limit request bodies at the proxy (for example, `client_max_body_size 10m` in Nginx) to protect file-upload endpoints. Configure firewall rules so PostgreSQL and Redis are private to the application network.

`DJANGO_CSP_ENFORCE` intentionally starts as `False`, so the policy is report-only and cannot break the current frontend or Django admin. Inspect browser CSP reports, add any genuinely required origins, then enable it.

## Security, limits and WhatsApp (new settings)

Add to the backend `.env` (defaults shown):

```dotenv
# Login: lock an account for 15 minutes after 3 wrong passwords
LOGIN_MAX_ATTEMPTS=3
LOGIN_LOCKOUT_MINUTES=15

# Forgot password: first code + 3 resends per 24h, 60s between sends
PASSWORD_RESET_MAX_RESENDS=3
PASSWORD_RESET_WINDOW_HOURS=24
PASSWORD_RESET_RESEND_COOLDOWN_SECONDS=60

# Phones are stored as international digits (91XXXXXXXXXX)
DEFAULT_PHONE_COUNTRY_CODE=91
LOCAL_PHONE_LENGTH=10

# Venue WhatsApp number users message after booking online (digits only)
WHATSAPP_SENDER_NUMBER=91XXXXXXXXXX

# Shared cache for throttling / lockouts when running >1 worker or server
REDIS_URL=redis://127.0.0.1:6379/1

# Behind nginx / a load balancer (number of trusted proxies)
USE_X_FORWARDED_FOR=True
NUM_PROXIES=1
```

`FRONTEND_URL` may list several origins separated by commas; the first one is used in emails and WhatsApp messages.

### How WhatsApp messages work

The backend returns a prefilled `https://wa.me/<number>?text=...` link (`whatsapp_url`) after:
admin add/edit user (password included), admin create/approve/cancel booking, event booking create/approve/reject, and loyalty point changes.
The admin panel shows a "Send on WhatsApp" card; one tap opens WhatsApp with the message ready. After a user books online they get a card to message the venue (`WHATSAPP_SENDER_NUMBER`).
wa.me links cannot send automatically. For fully automatic messages, replace `generate_whatsapp_url` in `gaming/utils/whatsapp.py` with a WhatsApp Business Cloud API call; the callers don't change.

### Load balancer / reverse proxy

- Health check: `GET /health/` (or `/api/auth/health/`) returns 200 when the app and database are up, 503 otherwise.
- Every response carries `X-Request-ID`; pass the proxy's request ID in the same header to correlate logs.
- Errors (5xx), slow requests (`SLOW_REQUEST_MS`, default 1000) and 401/403/429 are logged by the `gaming.requests` logger.
- Suggested nginx extras in front of gunicorn:

```nginx
limit_req_zone $binary_remote_addr zone=auth:10m rate=10r/m;
location /api/auth/login/            { limit_req zone=auth burst=5 nodelay; proxy_pass http://app; }
location /api/auth/forgot-password/  { limit_req zone=auth burst=3 nodelay; proxy_pass http://app; }
proxy_connect_timeout 5s;  proxy_read_timeout 60s;  client_max_body_size 10m;
```

- Run gunicorn with a timeout and several workers, e.g. `gunicorn dqdgaming.wsgi:application --workers 3 --timeout 60 --graceful-timeout 30`.
- Booking confirmation emails are sent from a background thread after the database commit, so slow email never blocks a request. For high volume, move `gaming/utils/tasks.py` to Celery/RQ.

### After pulling these changes

```bash
python manage.py migrate        # adds lockout fields + indexes, normalizes stored phone numbers
python manage.py test gaming
```

The phone migration skips (and logs) any number that would duplicate another user's; fix those by hand in the admin Users page.

### Device and login tracking

- Each sign-in stores the device in `user_devices`: browser + version, real OS version (Windows 11, Android 14 … from browser client hints), device model, screen size, time zone, language, first and latest IP. Last-seen time and latest IP refresh on authenticated requests (at most once per `DEVICE_ACTIVITY_INTERVAL_SECONDS`).
- Every login, failed password, lockout, sign-up, social login, logout and password reset is stored in `login_activities` and shown on the admin user detail.
- Client IP behind a proxy is read from the right of `X-Forwarded-For` using `NUM_PROXIES` (set it to the number of proxies in front of Django, e.g. 2 for Cloudflare + nginx). Set `TRUST_X_REAL_IP=True` only if nginx always overwrites `X-Real-IP`.
- Browsers never reveal a device's MAC address; `device_id` (issued at login, kept in the browser) identifies a device instead.
- Purge old history regularly, e.g. a daily cron: `python manage.py purge_login_activity --days 180`.

### One booking flow (games, combos, events, loyalty points)

All user bookings use the same three endpoints (business rules live in `gaming/services/booking.py`):

| Call | Purpose |
|------|---------|
| `GET /api/auth/user/book/options/?kind=game&id=<uuid>` | Title, price, min/max people, fixed date for events, points balance |
| `GET /api/auth/user/book/slots/?kind=game&id=<uuid>&date=YYYY-MM-DD` | Hourly start times and whether each is free |
| `POST /api/auth/user/book/` | `{kind, id, date, start_time, hours, members:[{name, phone}], notes}` |

`kind` is `game`, `combo`, `event` or `loyalty`. Combo bookings now block the games they include (and vice versa). Events accept guests, which use seats. The frontend page is `/user/book/:kind/:id`.

Settings: `BOOKING_OPEN_HOUR`, `BOOKING_CLOSE_HOUR`, `BOOKING_MAX_HOURS`, `BOOKING_MAX_DAYS_AHEAD`, `LOYALTY_POINTS_PER_HOUR`, `DRF_BOOKING_THROTTLE`.

### WhatsApp messages (admin → customer only)

Sent for: account created by admin, admin password reset, booking added by admin, booking confirmed/approved (game, combo, loyalty, event). The admin sees the full message in a preview card and taps **Send on WhatsApp**. Messages include an aligned details block, the player list, next steps, the venue address and contact number from `.env` (`WHATSAPP_SENDER_NUMBER`, `VENUE_NAME`, `VENUE_ADDRESS`).
