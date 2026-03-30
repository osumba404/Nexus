"""
News Aggregator Service
Fetches, merges and caches news from multiple APIs.
No articles are stored in the database — all content is fetched live.
"""
import hashlib
import logging
import concurrent.futures
from datetime import datetime, timedelta

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# ── Category mappings ────────────────────────────────────────────────────────
# NewsData.io categories
NEWSDATA_CATEGORIES = [
    'business', 'crime', 'domestic', 'education', 'entertainment',
    'environment', 'food', 'health', 'lifestyle', 'politics',
    'science', 'sports', 'technology', 'top', 'tourism', 'world',
]

# NewsAPI.org categories
NEWSAPI_CATEGORIES = [
    'business', 'entertainment', 'general', 'health',
    'science', 'sports', 'technology',
]

# Continent → NewsData.io region values
CONTINENT_REGIONS = {
    'africa': 'africa',
    'asia': 'asia',
    'europe': 'europe',
    'north-america': 'north-america',
    'south-america': 'south-america',
    'oceania': 'oceania',
    'middle-east': 'middle-east',
}

# Display labels
ALL_CATEGORIES = sorted(set(NEWSDATA_CATEGORIES + NEWSAPI_CATEGORIES))

CONTINENTS = [
    ('', 'All Continents'),
    ('africa', 'Africa'),
    ('asia', 'Asia'),
    ('europe', 'Europe'),
    ('north-america', 'North America'),
    ('south-america', 'South America'),
    ('oceania', 'Oceania'),
    ('middle-east', 'Middle East'),
]

POPULAR_COUNTRIES = [
    ('', 'All Countries'),
    ('ke', 'Kenya'),
    ('ng', 'Nigeria'),
    ('za', 'South Africa'),
    ('ug', 'Uganda'),
    ('tz', 'Tanzania'),
    ('gh', 'Ghana'),
    ('et', 'Ethiopia'),
    ('gb', 'United Kingdom'),
    ('us', 'United States'),
    ('in', 'India'),
    ('au', 'Australia'),
    ('cn', 'China'),
    ('fr', 'France'),
    ('de', 'Germany'),
    ('jp', 'Japan'),
    ('br', 'Brazil'),
    ('ca', 'Canada'),
    ('ae', 'UAE'),
    ('eg', 'Egypt'),
    ('ma', 'Morocco'),
]

SORT_OPTIONS = [
    ('publishedAt', 'Newest First'),
    ('relevancy', 'Most Relevant'),
    ('popularity', 'Most Popular'),
]


def _get_api_key(key_name: str) -> str:
    """Get API key from SiteSettings DB first, fallback to settings/env."""
    try:
        from core.models import SiteSettings
        site = SiteSettings.get_settings()
        db_key = getattr(site, key_name, '')
        if db_key:
            return db_key
    except Exception:
        pass
    # Fallback to settings
    env_map = {
        'newsdata_api_key': settings.NEWSDATA_API_KEY,
        'newsapi_key': settings.NEWSAPI_KEY,
    }
    return env_map.get(key_name, '')


def _make_cache_key(filters: dict) -> str:
    """Build a stable cache key from filter dict."""
    stable = '|'.join(f"{k}={v}" for k, v in sorted(filters.items()) if v)
    return 'news:' + hashlib.md5(stable.encode()).hexdigest()


def _normalize_article(raw: dict, source_api: str) -> dict | None:
    """Normalize an article from any API into a common format."""
    if source_api == 'newsdata':
        url = raw.get('link', '')
        title = raw.get('title', '')
        if not url or not title:
            return None
        return {
            'title': title,
            'excerpt': raw.get('description') or raw.get('content') or '',
            'url': url,
            'image_url': raw.get('image_url') or '',
            'source_name': raw.get('source_id', 'Unknown'),
            'source_url': '',
            'published_at': raw.get('pubDate', ''),
            'category': (raw.get('category') or [''])[0] if raw.get('category') else '',
            'country': (raw.get('country') or [''])[0] if raw.get('country') else '',
            'language': raw.get('language', ''),
            '_source_api': 'newsdata',
        }
    elif source_api == 'newsapi':
        url = raw.get('url', '')
        title = raw.get('title', '')
        if not url or not title or title == '[Removed]':
            return None
        source = raw.get('source', {})
        return {
            'title': title,
            'excerpt': raw.get('description') or raw.get('content') or '',
            'url': url,
            'image_url': raw.get('urlToImage') or '',
            'source_name': source.get('name', 'Unknown'),
            'source_url': '',
            'published_at': raw.get('publishedAt', ''),
            'category': '',
            'country': '',
            'language': '',
            '_source_api': 'newsapi',
        }
    return None


def _deduplicate(articles: list[dict]) -> list[dict]:
    """Remove duplicate articles by URL (case-insensitive)."""
    seen = set()
    result = []
    for article in articles:
        key = article['url'].lower().rstrip('/')
        if key not in seen:
            seen.add(key)
            result.append(article)
    return result


def _fetch_newsdata(filters: dict) -> list[dict]:
    """Fetch articles from NewsData.io API."""
    api_key = _get_api_key('newsdata_api_key')
    if not api_key:
        logger.warning('NewsData.io API key not configured')
        return []

    params = {
        'apikey': api_key,
        'language': filters.get('language') or 'en',
    }

    if filters.get('q'):
        params['q'] = filters['q']
    if filters.get('country'):
        params['country'] = filters['country']
    if filters.get('category'):
        params['category'] = filters['category']
    if filters.get('region'):
        params['region'] = filters['region']
    if filters.get('from_date'):
        params['from_date'] = filters['from_date']
    if filters.get('to_date'):
        params['to_date'] = filters['to_date']
    if filters.get('page_token'):
        params['page'] = filters['page_token']

    try:
        resp = requests.get(
            'https://newsdata.io/api/1/latest',
            params=params,
            timeout=8
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get('status') != 'success':
            logger.error('NewsData.io error: %s', data.get('message', 'unknown'))
            return []

        articles = []
        for item in data.get('results', []):
            normalized = _normalize_article(item, 'newsdata')
            if normalized:
                articles.append(normalized)
        return articles

    except requests.RequestException as e:
        logger.error('NewsData.io request failed: %s', e)
        return []
    except Exception as e:
        logger.error('NewsData.io unexpected error: %s', e)
        return []


def _fetch_newsapi(filters: dict) -> list[dict]:
    """Fetch articles from NewsAPI.org."""
    api_key = _get_api_key('newsapi_key')
    if not api_key:
        logger.warning('NewsAPI.org API key not configured')
        return []

    q = filters.get('q') or ''
    country = filters.get('country') or ''
    category = filters.get('category') or ''

    # Determine endpoint: top-headlines for country/category, everything for keyword search
    if q and not country and not category:
        endpoint = 'https://newsapi.org/v2/everything'
        params = {
            'apiKey': api_key,
            'q': q,
            'language': filters.get('language') or 'en',
            'sortBy': filters.get('sort_by') or 'publishedAt',
            'pageSize': 20,
        }
        if filters.get('from_date'):
            params['from'] = filters['from_date']
        if filters.get('to_date'):
            params['to'] = filters['to_date']
    else:
        endpoint = 'https://newsapi.org/v2/top-headlines'
        params = {'apiKey': api_key, 'pageSize': 20}
        if country:
            params['country'] = country
        if category:
            params['category'] = category
        if q:
            params['q'] = q

    try:
        resp = requests.get(endpoint, params=params, timeout=8)
        resp.raise_for_status()
        data = resp.json()

        if data.get('status') != 'ok':
            logger.error('NewsAPI.org error: %s', data.get('message', 'unknown'))
            return []

        articles = []
        for item in data.get('articles', []):
            normalized = _normalize_article(item, 'newsapi')
            if normalized:
                articles.append(normalized)
        return articles

    except requests.RequestException as e:
        logger.error('NewsAPI.org request failed: %s', e)
        return []
    except Exception as e:
        logger.error('NewsAPI.org unexpected error: %s', e)
        return []


class NewsAggregatorService:
    """
    Central service for fetching and aggregating news from multiple APIs.
    Results are cached to minimize API calls and maximize performance.
    """

    @staticmethod
    def get_news(
        q: str = '',
        country: str = 'ke',
        continent: str = '',
        category: str = '',
        language: str = 'en',
        from_date: str = '',
        to_date: str = '',
        sort_by: str = 'publishedAt',
        page: int = 1,
        page_size: int = None,
        force_refresh: bool = False,
    ) -> dict:
        """
        Fetch, merge, deduplicate and paginate news articles.

        Returns:
            {
                'articles': [...],
                'total': int,
                'page': int,
                'has_more': bool,
                'error': str | None,
                'sources_used': [str],
            }
        """
        if page_size is None:
            page_size = getattr(settings, 'NEWS_PAGE_SIZE', 12)

        filters = {
            'q': q.strip(),
            'country': country,
            'continent': continent,
            'category': category,
            'language': language,
            'from_date': from_date,
            'to_date': to_date,
            'sort_by': sort_by,
        }

        # Map continent to NewsData.io region
        if continent and not country:
            filters['region'] = CONTINENT_REGIONS.get(continent, continent)

        cache_key = _make_cache_key({**filters, 'page': page})
        ttl = getattr(settings, 'NEWS_CACHE_TTL', 180)

        if not force_refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                return cached

        # Parallel fetch from both APIs
        sources_used = []
        all_articles = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_newsdata = executor.submit(_fetch_newsdata, filters)
            future_newsapi = executor.submit(_fetch_newsapi, filters)

            newsdata_articles = future_newsdata.result()
            newsapi_articles = future_newsapi.result()

        if newsdata_articles:
            all_articles.extend(newsdata_articles)
            sources_used.append('NewsData.io')
        if newsapi_articles:
            all_articles.extend(newsapi_articles)
            sources_used.append('NewsAPI.org')

        # Deduplicate
        all_articles = _deduplicate(all_articles)

        # Sort
        def sort_key(a):
            return a.get('published_at') or ''

        all_articles.sort(key=sort_key, reverse=True)

        # Paginate
        total = len(all_articles)
        start = (page - 1) * page_size
        end = start + page_size
        page_articles = all_articles[start:end]

        result = {
            'articles': page_articles,
            'total': total,
            'page': page,
            'has_more': end < total,
            'error': None if (newsdata_articles or newsapi_articles) else (
                'No API keys configured. Add your NewsData.io or NewsAPI.org keys in Admin → Site Settings.'
                if not (_get_api_key('newsdata_api_key') or _get_api_key('newsapi_key'))
                else 'Could not fetch news. Please try again later.'
            ),
            'sources_used': sources_used,
        }

        cache.set(cache_key, result, ttl)
        return result

    @staticmethod
    def get_trending(country: str = 'ke', limit: int = 8) -> list[dict]:
        """Fetch a small set of trending/top headlines for the sidebar."""
        cache_key = f'news:trending:{country}'
        ttl = getattr(settings, 'NEWS_CACHE_TTL', 180)

        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        articles = _fetch_newsdata({'country': country, 'category': 'top', 'language': 'en'})
        if not articles:
            articles = _fetch_newsapi({'country': country})

        articles = _deduplicate(articles)[:limit]
        cache.set(cache_key, articles, ttl)
        return articles
