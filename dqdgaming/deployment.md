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
