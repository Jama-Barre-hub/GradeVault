"""Shared pytest configuration.

Nothing here changes how the application behaves. It only changes what
the tests pay for.
"""

import pytest


@pytest.fixture(autouse=True)
def _fast_password_hashing(settings):
    """Use a cheap hasher while testing.

    Production hashes passwords with PBKDF2 at 1.5 million iterations,
    which is deliberately slow: it is what makes a stolen hash expensive
    to crack. Paying that cost thousands of times in a test suite buys
    nothing, and it took the suite from 4 seconds to over 9 minutes once
    the seeder tests started creating accounts in bulk.

    A slow test suite is a test suite that stops being run, which quietly
    removes the protection the tests exist to provide.

    This affects tests only. Any test that needs to assert real hashing
    behaviour overrides `settings.PASSWORD_HASHERS` itself, and
    tests/test_settings.py asserts the production configuration directly.
    """
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def _sign_in_limits_off(settings):
    """Turn the failed-sign-in limiter off for most tests.

    django-axes wraps authentication and requires a request object, which
    Django's test client does not pass to client.login(). Leaving it on
    would make every test that signs somebody in fail for a reason that
    has nothing to do with what it is testing.

    tests/test_login_limits.py turns it back on, so the limiter itself is
    still exercised — just not by every unrelated test.
    """
    settings.AXES_ENABLED = False
