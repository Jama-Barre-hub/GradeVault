"""Tests for the language switcher.

GradeVault is for Somali schools, so the interface has to be available in
Somali. Every string in the templates and views is already wrapped for
translation, and the switching machinery is in place.

What is *not* in place is the Somali catalogue itself, and these tests
say so rather than implying otherwise. Django refuses to select a
language it has no compiled catalogue for, and it ships none for Somali,
so `so` is declared but inert until locale/so/LC_MESSAGES/django.mo is
produced. The test below records that, and is meant to be inverted the
day the catalogue lands.
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


# ---------- the gap, recorded rather than hidden ----------


def test_somali_has_no_catalogue_yet():
    """Django will not select a language it cannot load.

    This is why choosing Soomaali currently does nothing. It is a missing
    translation file, not a broken switcher.

    When locale/so/LC_MESSAGES/django.mo exists, this test will fail —
    and that failure is the signal to invert it into an assertion that
    Somali *is* selectable.
    """
    assert check_for_language("en") is True
    assert check_for_language("so") is False, (
        "A Somali catalogue now exists. Update this test to assert that "
        "Somali is selectable, and remove the note in README."
    )
