import hashlib

from rest_framework.throttling import SimpleRateThrottle


class OtpIPThrottle(SimpleRateThrottle):
    """Reset-code / reset-token attempts per client IP."""

    scope = "otp_ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class OtpEmailThrottle(SimpleRateThrottle):
    """Reset-code / reset-token attempts per email address, from any IP."""

    scope = "otp_email"

    def get_cache_key(self, request, view):
        data = request.data if hasattr(request.data, "get") else {}
        email = str(data.get("email") or "").strip().lower()
        if not email:
            return None  # nothing to key on; the IP throttle still applies
        return self.cache_format % {"scope": self.scope, "ident": hashlib.sha256(email.encode()).hexdigest()}
