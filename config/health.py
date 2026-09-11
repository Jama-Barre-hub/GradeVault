"""Liveness check for the hosting platform.

Render polls a URL to decide whether a deploy succeeded and whether the
running service is still healthy. Pointing that at `/login/` — as this
project did until now — makes the health of the service depend on
sessions, the sign-in rate limiter and template rendering. A broken
template would then take the site down for a reason unrelated to whether
it can actually serve.

This endpoint asks the one question that matters: is the process up and
can it reach its database? An application that cannot reach PostgreSQL
holds no marks and should not receive traffic, so that failure must
count as unhealthy rather than answering a cheerful 200.
"""

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache


@never_cache
def healthz(request):
    """200 when the database answers, 503 when it does not."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        # The exception itself is deliberately not returned. This URL is
        # public, and a database error can name hosts, users and schemas.
        # The traceback still reaches the logs through django.request.
        return JsonResponse({"status": "unhealthy"}, status=503)

    return JsonResponse({"status": "ok"})
