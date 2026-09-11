"""Read-only enforcement for the public demo.

The public demo exists so a stranger can sign in and see what GradeVault
does. That means handing working credentials to anyone who asks, which
in turn means anyone who asks can delete the demo school, blank a term's
marks, or forge audit entries — and the next visitor arrives to a broken
site.

So when DEMO_MODE is on, the whole deployment is read-only: every request
that could change data is refused, for every account including the
administrator. Not "demo accounts are restricted" — the entire site.
A single rule with no exceptions cannot be got wrong the way a per-account
allowance can, and there is nothing on the demo worth writing to.

Refusal is deliberately gentle. A visitor's first instinct is to open a
mark sheet, type a number and press Save; that is exactly the journey the
demo is advertising. Answering with a 403 wall would read as a broken
site. Instead the write is dropped, the page is redisplayed, and a
message explains why — so the visitor learns what the software does
without being able to damage it.

None of this is active in a real school deployment: DEMO_MODE defaults
to False, and every path below returns immediately when it is off.
"""

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

# One memorable sign-in per role, printed on the public page and created
# by `seed_demo`. They live here rather than in the seeder because two
# places need them — the page that advertises them and the command that
# creates them — and a demo whose published credentials do not match the
# accounts that exist is worse than no demo at all.
DEMO_ADMIN_USERNAME = "demo-admin"
DEMO_TEACHER_USERNAME = "demo-teacher"
DEMO_STUDENT_USERNAME = "demo-student"

# Ordered for the public page: the journey a visitor should take is
# teacher first (enter a mark), then student (see the grade), which is
# the claim PROPOSAL.md §9 makes.
DEMO_ACCOUNTS = (
    (_("Teacher"), DEMO_TEACHER_USERNAME),
    (_("Student"), DEMO_STUDENT_USERNAME),
    (_("Administrator"), DEMO_ADMIN_USERNAME),
)

# Methods that cannot change data. Everything else is refused.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Signing in and out are POSTs, and a demo nobody can sign in to is not a
# demo. Matched on the URL name, so the portal's `login` and the Django
# admin's `admin:login` are both covered without matching on path
# strings, which a new URL would silently slip past.
EXEMPT_URL_NAMES = frozenset({"login", "logout"})

DEMO_MESSAGE = _(
    "This is a public demo, so changes are not saved. "
    "Everything else works exactly as it would for a real school."
)


def demo_mode(request):
    """Template context: is this the public demo, and how to sign in.

    The credentials are supplied by the same module the seeder builds
    them from, so the page cannot advertise an account that was never
    created. Nothing is exposed at all when DEMO_MODE is off, so a real
    school's pages never mention demo accounts.
    """
    if not settings.DEMO_MODE:
        return {"demo_mode": False}

    return {
        "demo_mode": True,
        "demo_accounts": DEMO_ACCOUNTS,
        "demo_password": settings.DEMO_PASSWORD,
    }


class DemoReadOnlyMiddleware:
    """Refuses every data-changing request while DEMO_MODE is on."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Refuse before the view runs, so nothing is written at all.

        This runs as `process_view` rather than in `__call__` because
        only here has Django resolved the URL, and the exemption for
        signing in and out is expressed as a URL name.

        DEMO_MODE is read per request rather than once at startup. The
        cost is one attribute lookup; the gain is that a test can turn
        the demo on and off with `override_settings`, which is the only
        way the "off" case — a real school, where marks must save — gets
        proven rather than assumed.
        """
        if not settings.DEMO_MODE or request.method in SAFE_METHODS:
            return None

        match = request.resolver_match
        if match is not None and match.url_name in EXEMPT_URL_NAMES:
            return None

        messages.warning(request, DEMO_MESSAGE)

        # Back to the page the write came from. `request.get_full_path()`
        # is the resolved path of this request, not a value a visitor
        # supplied, so it cannot be pointed at another site.
        return redirect(request.get_full_path())
