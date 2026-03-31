from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from core.views import signup
from news.sitemaps import StaticViewSitemap, CategorySitemap, CountrySitemap

sitemaps = {
    'static':     StaticViewSitemap,
    'categories': CategorySitemap,
    'countries':  CountrySitemap,
}

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
    path('admin/', admin.site.urls),
    path('accounts/signup/', signup, name='signup'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('', include('news.urls', namespace='news')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
