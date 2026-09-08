"""Tests for the production configuration.

Security settings that only apply when DEBUG is off are the easiest kind
to get wrong, because nothing in development exercises them. A missing
SESSION_COOKIE_SECURE looks identical on a laptop and sends a signed-in
student's session over plain HTTP in production.

These load settings.py in isolation with DEBUG off and assert what it
produces, without disturbing the settings Django is already using.
"""

import importlib.util
import os
from pathlib import Path
from unittest import mock

import pytest

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "config" / "settings.py"

PRODUCTION_ENV = {
    "DJANGO_SECRET_KEY": "a" * 60,
    "DJANGO_DEBUG": "False",
    "DJANGO_ALLOWED_HOSTS": "gradevault.example.com",
}


def load_settings(**extra_env):
    """Execute settings.py in a throwaway module with a chosen environment."""
    env = {**PRODUCTION_ENV, **extra_env}

    with mock.patch.dict(os.environ, env, clear=False):
        for key in ("DATABASE_URL", "EMAIL_HOST"):
            if key not in env:
                os.environ.pop(key, None)

        spec = importlib.util.spec_from_file_location("_probe", SETTINGS_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

    return module


@pytest.fixture(scope="module")
def production():
    return load_settings()


# ---------- transport ----------


def test_plain_http_is_refused(production):
    """Marks and names must never cross the network in the clear."""
    assert production.SECURE_SSL_REDIRECT is True


def test_the_proxy_header_is_trusted_for_tls(production):
    """Render terminates TLS at its proxy and reports it in this header.

    Without it Django would think every request arrived over HTTP and
    redirect forever.
    """
    assert production.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")


def test_browsers_are_told_to_refuse_plain_http(production):
    assert production.SECURE_HSTS_SECONDS >= 31536000
    assert production.SECURE_HSTS_INCLUDE_SUBDOMAINS is True


# ---------- cookies ----------


def test_session_and_csrf_cookies_require_https(production):
    assert production.SESSION_COOKIE_SECURE is True
    assert production.CSRF_COOKIE_SECURE is True


def test_the_session_cookie_is_hidden_from_javascript(production):
    """A readable session cookie is one XSS bug away from being stolen."""
    assert production.SESSION_COOKIE_HTTPONLY is True


# ---------- headers ----------


def test_the_site_cannot_be_framed(production):
    assert production.X_FRAME_OPTIONS == "DENY"


def test_content_types_are_not_guessed(production):
    assert production.SECURE_CONTENT_TYPE_NOSNIFF is True


def test_referrers_do_not_leak_page_urls(production):
    """A student's results URL must not be handed to other sites."""
    assert production.SECURE_REFERRER_POLICY == "same-origin"


def test_csrf_trusts_only_the_configured_host(production):
    assert production.CSRF_TRUSTED_ORIGINS == ["https://gradevault.example.com"]


# ---------- static files ----------


def test_production_uses_the_hashed_static_backend(production):
    backend = production.STORAGES["staticfiles"]["BACKEND"]

    assert backend == "whitenoise.storage.CompressedManifestStaticFilesStorage"


def test_development_uses_the_forgiving_static_backend():
    """The manifest backend refuses anything collectstatic has not seen,
    which would make every page raise while developing."""
    development = load_settings(DJANGO_DEBUG="True")

    backend = development.STORAGES["staticfiles"]["BACKEND"]

    assert backend == "django.contrib.staticfiles.storage.StaticFilesStorage"


def test_whitenoise_sits_directly_after_the_security_middleware(production):
    middleware = production.MIDDLEWARE
    security = middleware.index("django.middleware.security.SecurityMiddleware")

    assert middleware[security + 1] == "whitenoise.middleware.WhiteNoiseMiddleware"


# ---------- development is left alone ----------


def test_development_does_not_force_https():
    """Local work over http://127.0.0.1 must keep working."""
    development = load_settings(DJANGO_DEBUG="True")

    assert getattr(development, "SECURE_SSL_REDIRECT", False) is False
    assert getattr(development, "SESSION_COOKIE_SECURE", False) is False


# ---------- database ----------


def test_sqlite_is_used_when_no_database_url_is_set(production):
    assert "sqlite3" in production.DATABASES["default"]["ENGINE"]


def test_database_url_replaces_sqlite_when_present():
    """The database is configuration, not a code change."""
    configured = load_settings(
        DATABASE_URL="postgres://user:pw@db.example.com:5432/gradevault",
        DATABASE_SSL="False",
    )

    assert "postgresql" in configured.DATABASES["default"]["ENGINE"]
    assert configured.DATABASES["default"]["NAME"] == "gradevault"


# ---------- email ----------


def test_mail_is_not_silently_discarded_in_production():
    """Nothing sends email yet. The console backend in production would
    quietly drop a future password reset instead of delivering it."""
    configured = load_settings(
        EMAIL_HOST="smtp.example.com", EMAIL_HOST_USER="noreply@example.com"
    )

    backend = configured.MAILERS["default"]["BACKEND"]

    assert backend == "django.core.mail.backends.smtp.EmailBackend"


# ---------- hosting platform ----------


def test_the_render_hostname_is_trusted_automatically():
    """Otherwise the first deploy returns 400 to every request until
    someone remembers to copy the hostname into a dashboard field.

    Render sets this variable itself, so it cannot be forged by a
    visitor the way a Host header can.
    """
    configured = load_settings(RENDER_EXTERNAL_HOSTNAME="gradevault.onrender.com")

    assert "gradevault.onrender.com" in configured.ALLOWED_HOSTS


def test_the_render_hostname_is_not_duplicated():
    """It may also be listed by hand once a custom domain is added."""
    configured = load_settings(
        DJANGO_ALLOWED_HOSTS="gradevault.onrender.com",
        RENDER_EXTERNAL_HOSTNAME="gradevault.onrender.com",
    )

    assert configured.ALLOWED_HOSTS.count("gradevault.onrender.com") == 1


def test_no_render_hostname_leaves_allowed_hosts_alone():
    assert load_settings().ALLOWED_HOSTS == ["gradevault.example.com"]


# ---------- demo mode ----------


def test_demo_mode_is_off_unless_asked_for():
    """A real school must be able to record marks. The demo guard is
    opt-in for that reason, and defaults off even in production."""
    assert load_settings().DEMO_MODE is False


def test_demo_mode_is_on_only_for_an_explicit_true():
    assert load_settings(DEMO_MODE="True").DEMO_MODE is True
    assert load_settings(DEMO_MODE="False").DEMO_MODE is False
    assert load_settings(DEMO_MODE="").DEMO_MODE is False
