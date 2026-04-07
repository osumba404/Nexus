"""
Nexus custom middleware.

RateLimitMiddleware  — IP-based rate limiting using Django's cache.
SlowRequestMiddleware — logs requests that exceed a configurable threshold.
"""
import logging
import time
from django.http import JsonResponse
from django.core.cache import cache

logger = logging.getLogger('nexus.requests')

# ── Rate limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT        = 120    # max requests per window
RATE_WINDOW       = 60     # window duration in seconds
RATE_BURST_PATHS  = {      # stricter limits for write endpoints
    '/interact/',
    '/article/comment/',
    '/preferences/',
    '/accounts/login/',
    '/accounts/signup/',
}
RATE_LIMIT_BURST  = 20     # max requests per window for burst paths
RATE_EXEMPT_PATHS = {      # never rate-limited
    '/health/',
    '/static/',
    '/media/',
    '/favicon.ico',
    '/robots.txt',
    '/sitemap.xml',
}


class RateLimitMiddleware:
    """
    Sliding-window rate limiter backed by Django's shared cache.

    With FileBasedCache (the default when running multiple Waitress workers),
    the counter is shared across all processes on the same machine.
    For cross-machine deployments use Redis as the cache backend.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info

        # Exempt paths bypass the limiter entirely
        if any(path.startswith(p) for p in RATE_EXEMPT_PATHS):
            return self.get_response(request)

        ip    = self._get_client_ip(request)
        limit = RATE_LIMIT_BURST if any(path.startswith(p) for p in RATE_BURST_PATHS) else RATE_LIMIT
        key   = f'rl:{ip}:{path.split("/")[1]}'   # per-IP, per-top-level-path segment

        try:
            count = cache.get_or_set(key, 0, RATE_WINDOW)
            if count >= limit:
                logger.warning('Rate limit hit: ip=%s path=%s count=%d', ip, path, count)
                return JsonResponse(
                    {'error': 'Too many requests. Please slow down.'},
                    status=429,
                    headers={
                        'Retry-After': str(RATE_WINDOW),
                        'X-RateLimit-Limit':     str(limit),
                        'X-RateLimit-Remaining': '0',
                        'X-RateLimit-Reset':     str(int(time.time()) + RATE_WINDOW),
                    },
                )
            # Increment without resetting TTL (approximate sliding window)
            cache.incr(key)
        except Exception:
            # Cache unavailable → fail open (don't block legitimate traffic)
            pass

        response = self.get_response(request)

        # Attach rate-limit headers to every response so clients can adapt
        try:
            remaining = max(0, limit - (cache.get(key) or 0))
            response['X-RateLimit-Limit']     = str(limit)
            response['X-RateLimit-Remaining'] = str(remaining)
            response['X-RateLimit-Reset']     = str(int(time.time()) + RATE_WINDOW)
        except Exception:
            pass

        return response

    @staticmethod
    def _get_client_ip(request) -> str:
        """Return the real client IP, respecting X-Forwarded-For from trusted proxies."""
        xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if xff:
            return xff.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '0.0.0.0')


# ── Slow-request logger ───────────────────────────────────────────────────────
SLOW_REQUEST_THRESHOLD = 2.0   # seconds


class SlowRequestMiddleware:
    """
    Logs any request that takes longer than SLOW_REQUEST_THRESHOLD seconds.
    Useful for identifying views that need caching or query optimisation.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        elapsed = time.monotonic() - start

        if elapsed >= SLOW_REQUEST_THRESHOLD:
            logger.warning(
                'Slow request: %s %s took %.2fs (status %d)',
                request.method,
                request.path,
                elapsed,
                response.status_code,
            )
            response['X-Response-Time'] = f'{elapsed:.3f}s'

        return response
