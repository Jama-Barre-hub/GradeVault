"""Tests for project configuration.

These guard the security decisions made in M0. They are deliberately the
first tests in the project: if configuration regresses, nothing else
matters.
"""

from django.conf import settings


def test_secret_key_is_not_djangos_insecure_default():
    """A generated key must be in use, not the placeholder Django ships."""
    assert settings.SECRET_KEY
    assert not settings.SECRET_KEY.startswith("django-insecure-")


def test_secret_key_is_long_enough():
    assert len(settings.SECRET_KEY) >= 50


def test_debug_is_a_boolean():
    """DEBUG must be a real bool, never the string 'False', which is truthy."""
    assert isinstance(settings.DEBUG, bool)


def test_timezone_is_somalia():
    assert settings.TIME_ZONE == "Africa/Mogadishu"
    assert settings.USE_TZ is True


def test_the_interface_is_english_only():
    """Somali was offered and withdrawn.

    The switcher worked but nothing was translated, so choosing it
    changed nothing visible. See tests/test_interface_language.py for the
    full reasoning; this asserts the settings agree with it.
    """
    assert [code for code, _name in settings.LANGUAGES] == ["en"]


def test_locale_middleware_is_enabled():
    assert "django.middleware.locale.LocaleMiddleware" in settings.MIDDLEWARE


def test_password_hashing_uses_django_validators():
    """Password rules must be Django's audited validators, not custom code."""
    assert len(settings.AUTH_PASSWORD_VALIDATORS) >= 4
