import base64
import hmac

from django.conf import settings
from django.http import HttpResponse


class BasicAuthMiddleware:
    """
    Site-wide HTTP Basic Auth gate, controlled by SITE_BASIC_AUTH_ENABLED.
    Temporary measure for while the site isn't meant to be publicly
    reachable yet -- entirely independent of the app's own login system
    (parents/coaches/admins still log in normally once past this gate).
    Toggle off later by flipping the env var, no code change needed.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.SITE_BASIC_AUTH_ENABLED or self._is_authorized(request):
            return self.get_response(request)
        response = HttpResponse("Authentication required.", status=401)
        response["WWW-Authenticate"] = 'Basic realm="Choice Select"'
        return response

    @staticmethod
    def _is_authorized(request):
        configured_user = settings.SITE_BASIC_AUTH_USER
        configured_password = settings.SITE_BASIC_AUTH_PASSWORD
        if not configured_user or not configured_password:
            # Enabled but misconfigured (blank credentials) -- fail closed
            # rather than ever treating a blank/absent header as a match.
            return False

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
        except ValueError:
            # Covers both malformed base64 (binascii.Error is a ValueError
            # subclass) and a missing ":" separator.
            return False

        return hmac.compare_digest(username, configured_user) and hmac.compare_digest(
            password, configured_password
        )
