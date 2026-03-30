from django.conf import settings
from .models import SiteSettings


def site_settings(request):
    """Inject site settings and news config into every template context."""
    try:
        site = SiteSettings.get_settings()
    except Exception:
        site = None

    return {
        'site_settings': site,
        'auto_refresh_seconds': getattr(site, 'auto_refresh_seconds', 180) if site else 180,
        'NEWS_AUTO_REFRESH': settings.NEWS_AUTO_REFRESH,
    }
