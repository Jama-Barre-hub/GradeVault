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
