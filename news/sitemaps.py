"""
Epicenter Nexus — sitemap definitions.
Static pages only (no news articles are stored in the DB).
"""
from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class StaticViewSitemap(Sitemap):
    priority    = 0.9
    changefreq  = 'always'   # live news aggregator — always fresh
    protocol    = 'https'

    def items(self):
        return [
            'news:home',
            'news:my_feed',
        ]

    def location(self, item):
        return reverse(item)


class CategorySitemap(Sitemap):
    """One URL per news category — helps Google index topic pages."""
    priority   = 0.7
    changefreq = 'hourly'
    protocol   = 'https'

    CATEGORIES = [
        'business', 'crime', 'domestic', 'education', 'entertainment',
        'environment', 'food', 'health', 'lifestyle', 'politics',
        'science', 'sports', 'technology', 'top', 'tourism', 'world',
    ]

    def items(self):
        return self.CATEGORIES

    def location(self, category):
        return f'/?category={category}'


class CountrySitemap(Sitemap):
    """Key country-filtered pages for geo-targeted ranking."""
    priority   = 0.6
    changefreq = 'hourly'
    protocol   = 'https'

    COUNTRIES = [
        'ke', 'ng', 'za', 'ug', 'tz', 'gh', 'et', 'rw',
        'gb', 'us', 'in', 'au',
    ]

    def items(self):
        return self.COUNTRIES

    def location(self, code):
        return f'/?country={code}'
