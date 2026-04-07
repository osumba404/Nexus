from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse, JsonResponse
from core.views import signup
from news.sitemaps import StaticViewSitemap, CategorySitemap, CountrySitemap
from django.db import connection as _db_connection

sitemaps = {
    'static':     StaticViewSitemap,
    'categories': CategorySitemap,
    'countries':  CountrySitemap,
}

def health_check(request):
    """Lightweight health endpoint used by Nginx upstream checks."""
    try:
        _db_connection.ensure_connection()
        db_ok = True
    except Exception:
        db_ok = False
    status = 200 if db_ok else 503
    return JsonResponse({'status': 'ok' if db_ok else 'degraded', 'db': db_ok}, status=status)


def robots_txt(request):
    lines = [
        'User-agent: *',
        'Allow: /',
        'Disallow: /admin/',
        'Disallow: /accounts/',
        'Disallow: /feed/',        # HTMX partial — not useful to crawlers
        'Disallow: /trending/',
        'Disallow: /interact/',
        'Disallow: /preferences/',
        '',
        f'Sitemap: https://epicenternexus.com/sitemap.xml',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain')

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('admin/', admin.site.urls),
    path('accounts/signup/', signup, name='signup'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('', include('news.urls', namespace='news')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
