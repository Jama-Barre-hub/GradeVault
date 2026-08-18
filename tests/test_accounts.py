"""Tests for the custom user model."""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()


def test_project_uses_the_custom_user_model():
    """Guards against the project silently reverting to django.contrib.auth."""
    assert settings.AUTH_USER_MODEL == "accounts.User"
    assert User.__module__ == "accounts.models"


def test_exactly_three_roles_exist():
    assert [r.value for r in User.Role] == ["admin", "teacher", "student"]


@pytest.mark.django_db
def test_role_helpers_are_mutually_exclusive():
    teacher = User.objects.create_user(
        username="tch-001", password="irrelevant-for-this-test", role=User.Role.TEACHER
    )

    assert teacher.is_teacher
    assert not teacher.is_admin
    assert not teacher.is_student


@pytest.mark.django_db
def test_a_student_needs_no_email_address():
    """Primary school students often have no email; it must never be required."""
    student = User.objects.create_user(
        username="STU-2026-0142",
        password="irrelevant-for-this-test",
        role=User.Role.STUDENT,
    )
    student.full_clean()  # raises ValidationError if email were required

    assert student.email == ""


@pytest.mark.django_db
def test_usernames_are_unique():
    from django.db import IntegrityError

    User.objects.create_user(username="STU-2026-0001", role=User.Role.STUDENT)

    with pytest.raises(IntegrityError):
        User.objects.create_user(username="STU-2026-0001", role=User.Role.STUDENT)


@pytest.mark.django_db
def test_passwords_are_hashed_never_stored_as_text():
    """Django must hash the password. This is asserted, not assumed."""
    raw = "a-real-looking-password-123"
    user = User.objects.create_user(
        username="tch-002", password=raw, role=User.Role.TEACHER
    )

    assert user.password != raw
    assert user.password.startswith("pbkdf2_")
    assert user.check_password(raw)


@pytest.mark.django_db
def test_a_superuser_is_automatically_an_administrator():
    """createsuperuser never prompts for role, so it must be set for us."""
    root = User.objects.create_superuser(username="root", password="dev-only-password")

    assert root.role == User.Role.ADMIN
    assert root.is_admin
    assert root.is_superuser
    assert root.is_staff


@pytest.mark.django_db
def test_str_shows_full_name_and_username_when_available():
    user = User.objects.create_user(
        username="STU-2026-0007",
        role=User.Role.STUDENT,
        first_name="Amina",
        last_name="Hassan",
    )

    assert str(user) == "Amina Hassan (STU-2026-0007)"


@pytest.mark.django_db
def test_str_falls_back_to_username_when_no_name_is_set():
    user = User.objects.create_user(username="STU-2026-0008", role=User.Role.STUDENT)

    assert str(user) == "STU-2026-0008"
