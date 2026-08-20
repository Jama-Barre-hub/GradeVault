"""The interface is English only, on purpose.

A Somali option was built and withdrawn. The switcher itself worked, but
almost none of the strings were translated, so choosing Soomaali changed
nothing a user could see. On a page whose argument is that this software
can be trusted with children's records, a control that appears broken
costs more than the feature was worth.

These tests hold that decision in place. They are meant to be deleted,
not worked around, on the day a finished Somali translation exists.
"""

import pytest
from django.conf import settings
from django.urls import NoReverseMatch, reverse


def test_only_english_is_offered():
    assert [code for code, _name in settings.LANGUAGES] == ["en"]


def test_there_is_no_language_switching_url():
    """Django's set_language endpoint is not routed, so nothing can post
    a language change to a catalogue that does not exist."""
    with pytest.raises(NoReverseMatch):
        reverse("set_language")


@pytest.mark.django_db
def test_no_page_shows_a_language_control(client):
    for page in [reverse("home"), reverse("login")]:
        body = client.get(page).content.decode()

        assert "Soomaali" not in body, f"{page} still offers a language switch"
        assert "lang-option" not in body, f"{page} still renders the switcher"


def test_translation_tags_are_kept_for_later():
    """The templates stay wrapped for translation. Removing the tags too
    would make adding Somali properly a rewrite rather than a task."""
    from pathlib import Path

    landing = Path(settings.BASE_DIR / "templates" / "landing.html").read_text(
        encoding="utf-8"
    )

    assert "{% translate" in landing
    assert "{% blocktranslate" in landing
