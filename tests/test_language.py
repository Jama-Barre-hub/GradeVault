"""Tests for the language switcher.

GradeVault is for Somali schools, so the interface has to be available in
Somali. Every string in the templates and views is already wrapped for
translation, and the switching machinery is in place.

The catalogue now exists, so Somali can be selected. Individual strings
are still being translated; an untranslated one falls back to English,
which is the correct behaviour and not a failure.
"""

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils.translation import check_for_language


def test_somali_is_offered_as_a_language():
    codes = [code for code, _name in settings.LANGUAGES]

    assert codes == ["en", "so"]


def test_the_locale_middleware_is_active():
    """Without it, a chosen language is forgotten on the next request."""
    assert "django.middleware.locale.LocaleMiddleware" in settings.MIDDLEWARE


def test_templates_can_see_the_current_language():
    """The switcher cannot mark the active language without this."""
    processors = settings.TEMPLATES[0]["OPTIONS"]["context_processors"]

    assert "django.template.context_processors.i18n" in processors


def test_the_project_declares_where_catalogues_live():
    assert settings.LOCALE_PATHS
    assert str(settings.LOCALE_PATHS[0]).endswith("locale")


@pytest.mark.django_db
def test_the_switcher_appears_on_the_sign_in_page(client):
    body = client.get(reverse("login")).content.decode()

    assert "Soomaali" in body
    assert "English" in body


@pytest.mark.django_db
def test_switching_language_is_remembered(client):
    """The choice is stored in a cookie, so it survives to the next page
    without a query string on every link. Django moved this from the
    session to a cookie in 4.0."""
    response = client.post(
        reverse("set_language"), {"language": "en", "next": "/login/"}
    )

    assert response.status_code == 302
    assert response.cookies[settings.LANGUAGE_COOKIE_NAME].value == "en"


@pytest.mark.django_db
def test_an_unknown_language_is_refused(client):
    client.post(reverse("set_language"), {"language": "zz", "next": "/login/"})

    response = client.get(reverse("login"))

    assert response.context["LANGUAGE_CODE"] != "zz"


# ---------- the catalogue ----------


def test_somali_can_be_selected():
    """Django refuses any language it cannot load a catalogue for.

    This asserted the opposite until locale/so/LC_MESSAGES/django.mo was
    compiled. Keeping the test guards against the catalogue being lost:
    without it the language button silently stops working, with no error
    anywhere to explain why.
    """
    assert check_for_language("en") is True
    assert check_for_language("so") is True, (
        "The Somali catalogue is missing. Run: python manage.py compilemessages -l so"
    )


@pytest.mark.django_db
def test_choosing_somali_takes_effect(client):
    client.post(reverse("set_language"), {"language": "so", "next": "/login/"})

    response = client.get(reverse("login"))

    assert response.context["LANGUAGE_CODE"] == "so"


@pytest.mark.django_db
def test_an_untranslated_string_falls_back_to_english(client):
    """Most strings are not translated yet. Falling back is correct: a
    blank interface would be far worse than an English one."""
    client.post(reverse("set_language"), {"language": "so", "next": "/login/"})

    body = client.get(reverse("login")).content.decode()

    assert "GradeVault" in body
    assert body.strip()
