"""
Epicenter Nexus — News Aggregator Service
==========================================
Fetches from 7 parallel sources, merges and caches results.
No articles are ever stored in the database.

Sources (all run in parallel):
  API keys required:
    1. NewsData.io      — 200 req/day free, multi-page pagination
    2. NewsAPI.org      — 100 req/day free, up to 100 articles/req
    3. GNews            — 100 req/day free
    4. Currents API     — 600 req/day free
    5. The News API     — 100 req/day free

  No key needed (always active):
    6. RSS feeds        — BBC, Reuters, Al Jazeera, Guardian, CNN, NPR,
                         Nation Africa, Standard Media, Daily Nation,
                         NTV Kenya, The Star Kenya, Business Daily Africa
"""
import hashlib
import logging
import threading as _threading
from pathlib import Path
from datetime import datetime, timezone

import feedparser
import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# ── Article content scraper ───────────────────────────────────────────────────

_SCRAPE_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

_CONTENT_CACHE_TTL = 6 * 3600  # 6 hours


def _best_image_url(attrib: dict, base_url: str) -> str:
    """
    Return the best-resolution image URL for an <img> element.

    Priority:
      1. Highest-width entry in srcset  (or data-srcset)
      2. data-src / data-lazy-src / data-original (lazy-load patterns)
      3. Plain src attribute
    All relative URLs are resolved against base_url.
    """
    from urllib.parse import urljoin

    def _resolve(u: str) -> str:
        if not u:
            return ''
        u = u.strip()
        if u.startswith('//'):
            return 'https:' + u
        if not u.startswith(('http://', 'https://')):
            return urljoin(base_url, u)
        return u

    def _parse_srcset(srcset: str) -> str:
        """Return URL of the widest descriptor in a srcset string."""
        best_url, best_w = '', 0
        for part in srcset.split(','):
            tokens = part.strip().split()
            if not tokens:
                continue
            url = tokens[0]
            w = 0
            if len(tokens) >= 2:
                desc = tokens[-1].lower()
                try:
                    if desc.endswith('w'):
                        w = int(desc[:-1])
                    elif desc.endswith('x'):
                        w = int(float(desc[:-1]) * 1000)  # pseudo-width
                except ValueError:
                    pass
            if w > best_w and url:
                best_w, best_url = w, url
        return _resolve(best_url) if best_url else ''

    # Check srcset first (highest quality)
    for attr in ('srcset', 'data-srcset'):
        v = attrib.get(attr, '')
        if v:
            u = _parse_srcset(v)
            if u:
                return u

    # Lazy-load patterns
    for attr in ('data-src', 'data-lazy-src', 'data-original',
                 'data-url', 'data-hi-res-src'):
        v = attrib.get(attr, '').strip()
        if v:
            return _resolve(v)

    # Plain src
    return _resolve(attrib.get('src', ''))


def _postprocess_article_html(html_str: str, base_url: str) -> str:
    """
    Post-process trafilatura's HTML output:

    Images
      • Pick highest-resolution URL from srcset/data-src/src
      • Make relative URLs absolute
      • Strip publisher-set width/height/style (let CSS control size)
      • Drop tracking pixels (explicit dimension ≤ 2px or ≤ 30px)
      • Drop duplicate images (same src appearing twice)
      • Add loading="lazy" decoding="async" and an onerror handler
        that removes the surrounding <figure> on broken load

    Captions
      • Collect all <figcaption> text; remove any <p> whose text
        is a close match — trafilatura sometimes duplicates captions
        as plain paragraphs

    Tables
      • Wrap every <table> in a horizontally-scrollable <div>
    """
    if not html_str:
        return html_str
    try:
        from lxml import html as lhtml

        root = lhtml.fromstring(f'<div>{html_str}</div>')

        # ── 1. Collect caption texts for deduplication ────────────────────
        caption_texts: set[str] = set()
        for fc in root.iter('figcaption'):
            t = (fc.text_content() or '').strip().lower()
            if t:
                caption_texts.add(t)

        # ── 2. Remove <p> elements whose text duplicates a caption ────────
        for p in list(root.iter('p')):
            t = (p.text_content() or '').strip().lower()
            if t and t in caption_texts:
                par = p.getparent()
                if par is not None:
                    par.remove(p)

        # ── 3. Process images ─────────────────────────────────────────────
        seen_srcs: set[str] = set()

        for img in list(root.iter('img')):
            attrib = img.attrib

            # Reject tracking/spacer pixels by declared dimension
            try:
                w = int(attrib.get('width', '999'))
                h = int(attrib.get('height', '999'))
                if w <= 30 or h <= 30:
                    _remove_node(img)
                    continue
            except ValueError:
                pass

            src = _best_image_url(dict(attrib), base_url)

            if not src:
                _remove_node(img)
                continue

            # Remove duplicate images
            if src in seen_srcs:
                _remove_node(img)
                continue
            seen_srcs.add(src)

            # Build clean attribute set
            alt = attrib.get('alt', '')
            img.attrib.clear()
            img.set('src', src)
            img.set('alt', alt)
            img.set('loading', 'lazy')
            img.set('decoding', 'async')
            # Remove the enclosing <figure> when the image fails to load
            img.set('onerror',
                    "var f=this.closest('figure')||this.parentElement;"
                    "if(f)f.style.display='none';")

        # ── 4. Remove empty <figure> elements left after image removal ────
        for fig in list(root.iter('figure')):
            if not list(fig.iter('img')) and not (fig.text_content() or '').strip():
                _remove_node(fig)

        # ── 5. Wrap tables in scrollable container ────────────────────────
        for table in list(root.iter('table')):
            par = table.getparent()
            if par is None:
                continue
            idx = list(par).index(table)
            wrapper = lhtml.Element('div')
            wrapper.set('class', 'article-table-wrap')
            par.remove(table)
            wrapper.append(table)
            par.insert(idx, wrapper)

        # ── 6. Normalise paragraphs ───────────────────────────────────────
        # Trafilatura sometimes emits content in <div> wrappers or as bare
        # text nodes instead of <p> elements.  Walk every node and:
        #   a) rename bare/unstyled <div> containers → <p>
        #   b) collect text that lives outside any block element and wrap it
        #   c) split on consecutive <br> tags → separate <p> elements
        _BLOCK = {'p','h1','h2','h3','h4','h5','h6','ul','ol','li',
                  'blockquote','figure','table','pre','div','section',
                  'article','header','footer','aside'}

        def _is_inline_or_text(el):
            return el.tag not in _BLOCK

        # a) Convert <div> that contain only inline content → <p>
        for div in list(root.iter('div')):
            if div.get('class') in ('article-table-wrap',):
                continue
            has_block_child = any(c.tag in _BLOCK for c in div)
            if not has_block_child:
                div.tag = 'p'

        # b) Wrap any remaining root.text / element.tail in <p> elements
        def _wrap_tail(parent):
            children = list(parent)
            # Handle parent.text (text before first child)
            if (parent.text or '').strip():
                p = lhtml.Element('p')
                p.text = parent.text
                parent.text = None
                parent.insert(0, p)
                children = list(parent)  # refresh

            for i, child in enumerate(children):
                if (child.tail or '').strip():
                    p = lhtml.Element('p')
                    p.text = child.tail
                    child.tail = None
                    parent.insert(i + 1, p)

        _wrap_tail(root)

        # c) Split on double-<br> patterns inside <p> elements
        for p in list(root.iter('p')):
            brs = [c for c in p if c.tag == 'br']
            if len(brs) < 2:
                continue
            # Serialise → split on <br><br> → re-parse as sibling <p>s
            raw = lhtml.tostring(p, encoding='unicode', method='html')
            # Replace 2+ consecutive <br> with a paragraph separator marker
            import re as _re
            raw_inner = _re.sub(r'<p[^>]*>', '', raw)
            raw_inner = _re.sub(r'</p>', '', raw_inner)
            raw_inner = _re.sub(r'(<br\s*/?>){2,}', '\x00', raw_inner,
                                flags=_re.IGNORECASE)
            if '\x00' not in raw_inner:
                continue
            parts = [t.strip() for t in raw_inner.split('\x00') if t.strip()]
            if len(parts) < 2:
                continue
            parent = p.getparent()
            if parent is None:
                continue
            idx = list(parent).index(p)
            parent.remove(p)
            for offset, part in enumerate(parts):
                np = lhtml.fromstring(f'<p>{part}</p>')
                parent.insert(idx + offset, np)

        # Serialise (strip the wrapper <div>)
        inner = (root.text or '') + ''.join(
            lhtml.tostring(child, encoding='unicode', method='html')
            for child in root
        )
        return inner

    except Exception as exc:
        logger.debug('_postprocess_article_html error: %s', exc)
        return html_str


def _remove_node(el) -> None:
    """Remove *el* from its parent; no-op if already detached."""
    par = el.getparent()
    if par is not None:
        par.remove(el)


def fetch_article_content(url: str) -> dict:
    """
    Fetch and extract the full article body from *url* using trafilatura.
    Returns a dict::

        {
            'html':    '<p>…</p>',   # sanitised HTML — empty str on failure
            'author':  'Jane Doe',   # may be empty
            'date':    '2026-03-31', # may be empty
            'failed':  False,        # True when extraction produced nothing
        }

    Results are cached in Django's cache for _CONTENT_CACHE_TTL seconds so
    repeated visits to the same article page don't hammer the origin server.
    """
    cache_key = 'article_content_v4_' + hashlib.md5(url.encode()).hexdigest()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = {'html': '', 'author': '', 'date': '', 'failed': True}
    try:
        import trafilatura
        import json as _json

        # Use trafilatura's own fetcher first (handles redirects + encoding)
        downloaded = trafilatura.fetch_url(url)

        # If trafilatura's fetcher fails (e.g. JS-gated), fall back to requests
        if not downloaded:
            try:
                resp = requests.get(url, headers=_SCRAPE_HEADERS, timeout=15)
                resp.raise_for_status()
                downloaded = resp.text
            except Exception:
                pass

        if downloaded:
            # ── Metadata (author, date) ───────────────────────────────────
            meta_json = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=True,
                include_images=True,
                include_links=True,
                include_formatting=True,
                no_fallback=False,
                with_metadata=True,
                output_format='json',
            )

            # ── Full HTML body ────────────────────────────────────────────
            html_out = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=True,
                include_images=True,       # ← images now included
                include_links=True,        # ← hyperlinks preserved
                include_formatting=True,   # ← bold / italic / br preserved
                no_fallback=False,
                with_metadata=False,
                output_format='html',
            )

            author = ''
            date   = ''
            if meta_json:
                try:
                    meta   = _json.loads(meta_json)
                    author = meta.get('author') or ''
                    date   = (meta.get('date') or '')[:10]
                except Exception:
                    pass

            if html_out and html_out.strip():
                # Fix relative image URLs, add lazy-load attrs, wrap tables
                html_out = _postprocess_article_html(html_out, url)
                result = {
                    'html':   html_out,
                    'author': author,
                    'date':   date,
                    'failed': False,
                }

    except Exception as exc:
        logger.warning('fetch_article_content error for %s: %s', url, exc)

    cache.set(cache_key, result, _CONTENT_CACHE_TTL)
    return result


# ── Categories ────────────────────────────────────────────────────────────────
NEWSDATA_CATEGORIES = [
    'business', 'crime', 'domestic', 'education', 'entertainment',
    'environment', 'food', 'health', 'lifestyle', 'politics',
    'science', 'sports', 'technology', 'top', 'tourism', 'world',
]
NEWSAPI_CATEGORIES = [
    'business', 'entertainment', 'general', 'health',
    'science', 'sports', 'technology',
]
ALL_CATEGORIES = sorted(set(NEWSDATA_CATEGORIES + NEWSAPI_CATEGORIES))

# ── Geo options ───────────────────────────────────────────────────────────────
CONTINENT_REGIONS = {
    'africa': 'africa', 'asia': 'asia', 'europe': 'europe',
    'north-america': 'north-america', 'south-america': 'south-america',
    'oceania': 'oceania', 'middle-east': 'middle-east',
}

CONTINENTS = [
    ('', 'All Continents'), ('africa', 'Africa'), ('asia', 'Asia'),
    ('europe', 'Europe'), ('north-america', 'North America'),
    ('south-america', 'South America'), ('oceania', 'Oceania'),
    ('middle-east', 'Middle East'),
]

POPULAR_COUNTRIES = [
    ('', 'All Countries'),
    ('ke', 'Kenya'), ('ng', 'Nigeria'), ('za', 'South Africa'),
    ('ug', 'Uganda'), ('tz', 'Tanzania'), ('gh', 'Ghana'),
    ('et', 'Ethiopia'), ('rw', 'Rwanda'), ('eg', 'Egypt'), ('ma', 'Morocco'),
    ('gb', 'United Kingdom'), ('us', 'United States'), ('in', 'India'),
    ('au', 'Australia'), ('cn', 'China'), ('fr', 'France'),
    ('de', 'Germany'), ('jp', 'Japan'), ('br', 'Brazil'),
    ('ca', 'Canada'), ('ae', 'UAE'), ('za', 'South Africa'),
]

SORT_OPTIONS = [
    ('publishedAt', 'Newest First'),
    ('relevancy', 'Most Relevant'),
    ('popularity', 'Most Popular'),
]

# ── RSS feed registry ─────────────────────────────────────────────────────────
RSS_FEEDS = [
    # Global / International
    {'url': 'http://feeds.bbci.co.uk/news/rss.xml',            'source': 'BBC News',         'category': 'top'},
    {'url': 'http://feeds.bbci.co.uk/news/world/rss.xml',      'source': 'BBC World',        'category': 'world'},
    {'url': 'http://feeds.bbci.co.uk/news/technology/rss.xml', 'source': 'BBC Tech',         'category': 'technology'},
    {'url': 'http://feeds.bbci.co.uk/news/business/rss.xml',   'source': 'BBC Business',     'category': 'business'},
    {'url': 'https://www.aljazeera.com/xml/rss/all.xml',        'source': 'Al Jazeera',       'category': 'world'},
    {'url': 'https://www.theguardian.com/world/rss',            'source': 'The Guardian',     'category': 'world'},
    {'url': 'https://www.theguardian.com/technology/rss',       'source': 'Guardian Tech',    'category': 'technology'},
    {'url': 'https://rss.cnn.com/rss/edition.rss',             'source': 'CNN',              'category': 'top'},
    {'url': 'https://rss.cnn.com/rss/money_news_international.rss', 'source': 'CNN Money',   'category': 'business'},
    {'url': 'https://feeds.npr.org/1001/rss.xml',              'source': 'NPR',              'category': 'top'},
    {'url': 'https://feeds.npr.org/1019/rss.xml',              'source': 'NPR World',        'category': 'world'},
    # Africa / Kenya
    {'url': 'https://nation.africa/kenya/rss.xml',             'source': 'Nation Africa',    'category': 'top',      'country': 'ke'},
    {'url': 'https://nation.africa/kenya/business/rss.xml',    'source': 'Nation Business',  'category': 'business', 'country': 'ke'},
    {'url': 'https://www.standardmedia.co.ke/rss/headlines',   'source': 'Standard Media',   'category': 'top',      'country': 'ke'},
    {'url': 'https://www.standardmedia.co.ke/rss/business',    'source': 'Standard Business','category': 'business', 'country': 'ke'},
    {'url': 'https://www.the-star.co.ke/rss/',                 'source': 'The Star Kenya',   'category': 'top',      'country': 'ke'},
    {'url': 'https://www.businessdailyafrica.com/rss/',         'source': 'Business Daily',   'category': 'business', 'country': 'ke'},
    {'url': 'https://ntv.nation.africa/rss/',                  'source': 'NTV Kenya',        'category': 'top',      'country': 'ke'},
    {'url': 'https://www.capitalfm.co.ke/news/feed/',          'source': 'Capital FM',       'category': 'top',      'country': 'ke'},
    # Tech
    {'url': 'https://techcrunch.com/feed/',                    'source': 'TechCrunch',       'category': 'technology'},
    {'url': 'https://www.wired.com/feed/rss',                  'source': 'Wired',            'category': 'technology'},
    {'url': 'https://feeds.arstechnica.com/arstechnica/index', 'source': 'Ars Technica',     'category': 'technology'},
    # Science / Health
    {'url': 'https://www.sciencedaily.com/rss/top/science.xml','source': 'Science Daily',    'category': 'science'},
    {'url': 'https://feeds.webmd.com/rss/rss.aspx?RSSSource=RSS_PUBLIC', 'source': 'WebMD', 'category': 'health'},
    # Sports
    {'url': 'https://www.espn.com/espn/rss/news',              'source': 'ESPN',             'category': 'sports'},
    {'url': 'https://feeds.bbci.co.uk/sport/rss.xml',          'source': 'BBC Sport',        'category': 'sports'},
]


# ── Key resolution ────────────────────────────────────────────────────────────
def _resolve_keys() -> dict:
    """
    Resolve all API keys in the main request thread.
    Checks Admin SiteSettings first, then .env, then reads .env file directly.
    Returns dict with all key names → values (empty string if not configured).
    """
    keys = {
        'newsdata': '', 'newsapi': '', 'gnews': '',
        'currents': '', 'thenewsapi': '',
    }

    # 1. Try SiteSettings DB
    try:
        from core.models import SiteSettings
        site = SiteSettings.get_settings()
        keys['newsdata']   = (site.newsdata_api_key or '').strip()
        keys['newsapi']    = (site.newsapi_key or '').strip()
        keys['gnews']      = (site.gnews_api_key or '').strip()
        keys['currents']   = (site.currents_api_key or '').strip()
        keys['thenewsapi'] = (site.thenewsapi_key or '').strip()
    except Exception as e:
        logger.warning('SiteSettings lookup failed: %s', e)

    # 2. Fall back to Django settings (loaded from .env on startup)
    setting_map = {
        'newsdata':   'NEWSDATA_API_KEY',
        'newsapi':    'NEWSAPI_KEY',
        'gnews':      'GNEWS_API_KEY',
        'currents':   'CURRENTS_API_KEY',
        'thenewsapi': 'THENEWSAPI_KEY',
    }
    for k, setting_name in setting_map.items():
        if not keys[k]:
            keys[k] = (getattr(settings, setting_name, '') or '').strip()

    # 3. Last resort: read .env file directly
    if not any(keys.values()):
        keys = _read_env_file_direct(keys)

    active = [k for k, v in keys.items() if v]
    print(f'[Nexus] keys resolved: {active or "none (RSS only)"}', flush=True)
    return keys


def _read_env_file_direct(keys: dict) -> dict:
    """Read API keys directly from .env as final fallback."""
    try:
        env_path = Path(settings.BASE_DIR) / '.env'
        if not env_path.exists():
            return keys
        mapping = {
            'NEWSDATA_API_KEY': 'newsdata', 'NEWSAPI_KEY': 'newsapi',
            'GNEWS_API_KEY': 'gnews', 'CURRENTS_API_KEY': 'currents',
            'THENEWSAPI_KEY': 'thenewsapi',
        }
        with open(env_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') or '=' not in line:
                    continue
                env_key, _, val = line.partition('=')
                env_key = env_key.strip()
                val = val.strip().strip('"').strip("'")
                if env_key in mapping and not keys[mapping[env_key]]:
                    keys[mapping[env_key]] = val
    except Exception as e:
        logger.warning('Failed to read .env directly: %s', e)
    return keys


# ── Normalisation ─────────────────────────────────────────────────────────────
def _normalize(raw: dict, source_api: str) -> dict | None:
    """Normalize an article from any source into a common schema."""
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
            'source_name': raw.get('source_id') or raw.get('source_name') or 'NewsData',
            'published_at': raw.get('pubDate', ''),
            'category': ((raw.get('category') or [''])[0]) if raw.get('category') else '',
            'country': ((raw.get('country') or [''])[0]) if raw.get('country') else '',
        }

    if source_api == 'newsapi':
        url = raw.get('url', '')
        title = raw.get('title', '')
        if not url or not title or title == '[Removed]':
            return None
        src = raw.get('source', {})
        return {
            'title': title,
            'excerpt': raw.get('description') or '',
            'url': url,
            'image_url': raw.get('urlToImage') or '',
            'source_name': src.get('name', 'NewsAPI'),
            'published_at': raw.get('publishedAt', ''),
            'category': '',
            'country': '',
        }

    if source_api == 'gnews':
        url = raw.get('url', '')
        title = raw.get('title', '')
        if not url or not title:
            return None
        src = raw.get('source', {})
        return {
            'title': title,
            'excerpt': raw.get('description') or '',
            'url': url,
            'image_url': raw.get('image') or '',
            'source_name': src.get('name', 'GNews'),
            'published_at': raw.get('publishedAt', ''),
            'category': '',
            'country': '',
        }

    if source_api == 'currents':
        url = raw.get('url', '')
        title = raw.get('title', '')
        if not url or not title:
            return None
        cats = raw.get('category', [])
        return {
            'title': title,
            'excerpt': raw.get('description') or '',
            'url': url,
            'image_url': raw.get('image') or '',
            'source_name': 'Currents API',
            'published_at': raw.get('published', ''),
            'category': cats[0] if cats else '',
            'country': '',
        }

    if source_api == 'thenewsapi':
        url = raw.get('url', '')
        title = raw.get('title', '')
        if not url or not title:
            return None
        cats = raw.get('categories', [])
        return {
            'title': title,
            'excerpt': raw.get('description') or raw.get('snippet') or '',
            'url': url,
            'image_url': raw.get('image_url') or '',
            'source_name': raw.get('source', 'TheNewsAPI'),
            'published_at': raw.get('published_at', ''),
            'category': cats[0] if cats else '',
            'country': '',
        }

    if source_api == 'rss':
        url = raw.get('link', '')
        title = raw.get('title', '')
        if not url or not title:
            return None
        pub = ''
        if raw.get('published_parsed'):
            try:
                dt = datetime(*raw['published_parsed'][:6], tzinfo=timezone.utc)
                pub = dt.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                pass
        return {
            'title': title,
            'excerpt': raw.get('summary') or '',
            'url': url,
            'image_url': raw.get('media_thumbnail', [{}])[0].get('url', '') if raw.get('media_thumbnail') else '',
            'source_name': raw.get('_feed_source', 'RSS'),
            'published_at': pub,
            'category': raw.get('_feed_category', ''),
            'country': raw.get('_feed_country', ''),
        }

    return None


def _deduplicate(articles: list[dict]) -> list[dict]:
    seen, result = set(), []
    for a in articles:
        key = a['url'].lower().rstrip('/')
        if key not in seen:
            seen.add(key)
            result.append(a)
    return result


def _make_cache_key(filters: dict) -> str:
    stable = '|'.join(f"{k}={v}" for k, v in sorted(filters.items()) if v)
    return 'news:v2:' + hashlib.md5(stable.encode()).hexdigest()


def _make_user_cache_key(filters: dict, user_key: str) -> str:
    """Per-user/session cache key so users get independent caches."""
    stable = '|'.join(f"{k}={v}" for k, v in sorted(filters.items()) if v)
    return f'news:v2:{user_key}:' + hashlib.md5(stable.encode()).hexdigest()


def _sort_by_freshness(articles: list[dict], seen_urls: set) -> list[dict]:
    """Put unseen articles first, then seen ones — both groups newest-first."""
    unseen = [a for a in articles if a['url'] not in seen_urls]
    seen   = [a for a in articles if a['url'] in seen_urls]
    return unseen + seen




# ── Individual fetchers ───────────────────────────────────────────────────────
def _fetch_newsdata(filters: dict, api_key: str, max_pages: int = 5) -> list[dict]:
    """NewsData.io — follows nextPage tokens for up to max_pages pages."""
    if not api_key:
        return []

    base = {
        'apikey': api_key,
        'language': filters.get('language') or 'en',
    }
    if filters.get('q'):        base['q'] = filters['q']
    if filters.get('country'):  base['country'] = filters['country']
    if filters.get('category'): base['category'] = filters['category']
    if filters.get('region'):   base['region'] = filters['region']
    if filters.get('from_date'):base['from_date'] = filters['from_date']
    if filters.get('to_date'):  base['to_date'] = filters['to_date']

    articles, next_token = [], None
    for page_num in range(max_pages):
        params = dict(base)
        if next_token:
            params['page'] = next_token
        try:
            r = requests.get('https://newsdata.io/api/1/news', params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.error('NewsData.io page %d failed: %s', page_num + 1, e)
            break
        if data.get('status') != 'success':
            logger.error('NewsData.io error: %s', data.get('message'))
            break
        for item in data.get('results', []):
            n = _normalize(item, 'newsdata')
            if n:
                articles.append(n)
        next_token = data.get('nextPage')
        if not next_token:
            break
    return articles


def _fetch_newsapi(filters: dict, api_key: str) -> list[dict]:
    """NewsAPI.org — 100 articles per call."""
    if not api_key:
        return []

    q = filters.get('q') or ''
    country = filters.get('country') or ''
    category = filters.get('category') or ''

    if q and not country and not category:
        endpoint = 'https://newsapi.org/v2/everything'
        params = {
            'apiKey': api_key, 'q': q, 'pageSize': 100,
            'language': filters.get('language') or 'en',
            'sortBy': filters.get('sort_by') or 'publishedAt',
        }
        if filters.get('from_date'): params['from'] = filters['from_date']
        if filters.get('to_date'):   params['to']   = filters['to_date']
    else:
        endpoint = 'https://newsapi.org/v2/top-headlines'
        params = {'apiKey': api_key, 'pageSize': 100}
        if country:  params['country']  = country
        if category: params['category'] = category
        if q:        params['q']        = q

    try:
        r = requests.get(endpoint, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get('status') != 'ok':
            logger.error('NewsAPI.org error: %s', data.get('message'))
            return []
        return [n for item in data.get('articles', []) if (n := _normalize(item, 'newsapi'))]
    except Exception as e:
        logger.error('NewsAPI.org failed: %s', e)
        return []


def _fetch_gnews(filters: dict, api_key: str) -> list[dict]:
    """GNews (gnews.io) — up to 10 articles on free tier."""
    if not api_key:
        return []

    q = filters.get('q') or filters.get('category') or 'latest'
    params = {
        'token': api_key,
        'lang': filters.get('language') or 'en',
        'max': 10,
        'q': q,
    }
    if filters.get('country'):
        params['country'] = filters['country']
    if filters.get('from_date'):
        params['from'] = filters['from_date'] + 'T00:00:00Z'
    if filters.get('to_date'):
        params['to'] = filters['to_date'] + 'T23:59:59Z'

    try:
        r = requests.get('https://gnews.io/api/v4/top-headlines', params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        return [n for item in data.get('articles', []) if (n := _normalize(item, 'gnews'))]
    except Exception as e:
        logger.error('GNews failed: %s', e)
        return []


def _fetch_currents(filters: dict, api_key: str) -> list[dict]:
    """Currents API (currentsapi.services) — up to 200 articles."""
    if not api_key:
        return []

    params = {
        'apiKey': api_key,
        'language': filters.get('language') or 'en',
    }
    if filters.get('q'):        params['keywords'] = filters['q']
    if filters.get('country'):  params['country']  = filters['country']
    if filters.get('category'): params['category'] = filters['category']
    if filters.get('from_date'):params['start_date'] = filters['from_date']
    if filters.get('to_date'):  params['end_date']   = filters['to_date']

    try:
        r = requests.get('https://api.currentsapi.services/v1/latest-news', params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get('status') != 'ok':
            logger.error('Currents API error: %s', data.get('message'))
            return []
        return [n for item in data.get('news', []) if (n := _normalize(item, 'currents'))]
    except Exception as e:
        logger.error('Currents API failed: %s', e)
        return []


def _fetch_thenewsapi(filters: dict, api_key: str) -> list[dict]:
    """The News API (thenewsapi.com)."""
    if not api_key:
        return []

    params = {
        'api_token': api_key,
        'language': filters.get('language') or 'en',
        'limit': 3,  # free tier max
    }
    if filters.get('q'):        params['search']     = filters['q']
    if filters.get('country'):  params['locale']     = filters['country']
    if filters.get('category'): params['categories'] = filters['category']
    if filters.get('from_date'):params['published_after'] = filters['from_date']

    try:
        r = requests.get('https://api.thenewsapi.com/v1/news/top', params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        return [n for item in data.get('data', []) if (n := _normalize(item, 'thenewsapi'))]
    except Exception as e:
        logger.error('TheNewsAPI failed: %s', e)
        return []


def _fetch_rss(filters: dict) -> list[dict]:
    """
    Fetch from all RSS feeds in parallel.
    Applies country filter: if country set, includes global feeds + matching country feeds.
    Applies category filter: prefers feeds tagged with matching category.
    """
    country = filters.get('country', '').lower()
    category = filters.get('category', '').lower()
    q = (filters.get('q') or '').lower()

    # Pick relevant feeds
    feeds_to_fetch = []
    for feed in RSS_FEEDS:
        feed_country = feed.get('country', '')
        # Country filter: include if feed has no country tag (global) or matches
        if country and feed_country and feed_country != country:
            continue
        feeds_to_fetch.append(feed)

    articles = []

    def _parse_one(feed_meta: dict) -> list[dict]:
        feed_articles = []
        try:
            parsed = feedparser.parse(feed_meta['url'])
            for entry in parsed.entries[:15]:  # max 15 per feed
                entry['_feed_source'] = feed_meta['source']
                entry['_feed_category'] = feed_meta.get('category', '')
                entry['_feed_country'] = feed_meta.get('country', '')
                n = _normalize(entry, 'rss')
                if n:
                    # Keyword filter
                    if q and q not in n['title'].lower() and q not in n['excerpt'].lower():
                        continue
                    # Category filter (soft — prefer matching but don't exclude)
                    feed_articles.append(n)
        except Exception as e:
            logger.warning('RSS %s failed: %s', feed_meta['source'], e)
        return feed_articles

    _rss_results: list = []
    _rss_lock = _threading.Lock()

    def _run_rss(feed_meta):
        try:
            result = _parse_one(feed_meta)
            with _rss_lock:
                _rss_results.extend(result)
        except Exception:
            pass

    _rss_threads = [_threading.Thread(target=_run_rss, args=(f,), daemon=True)
                    for f in feeds_to_fetch]
    try:
        for t in _rss_threads:
            t.start()
        for t in _rss_threads:
            t.join(timeout=20)
    except RuntimeError:
        # Python 3.14: interpreter shutting down during dev-server reload.
        # Fall back to sequential so the request still completes.
        for f in feeds_to_fetch:
            _run_rss(f)
    articles.extend(_rss_results)

    return articles


# ── Main service ──────────────────────────────────────────────────────────────
class NewsAggregatorService:
    """
    Fetches from all configured sources in parallel, merges, deduplicates,
    sorts and paginates. Only successful responses are cached.
    """

    SOURCE_LABELS = {
        'newsdata': 'NewsData.io',
        'newsapi':  'NewsAPI.org',
        'gnews':    'GNews',
        'currents': 'Currents API',
        'thenewsapi': 'The News API',
        'rss':      'RSS Feeds',
    }

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
        user_key: str = 'anon',
        seen_urls: set = None,
    ) -> dict:
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
        if continent and not country:
            filters['region'] = CONTINENT_REGIONS.get(continent, continent)

        cache_key = _make_user_cache_key({**filters, 'page': page}, user_key)
        ttl = getattr(settings, 'NEWS_CACHE_TTL', 180)

        if not force_refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                return cached

        # Resolve keys once in the main thread
        keys = _resolve_keys()

        # Launch all sources in parallel
        all_articles: list[dict] = []
        sources_used: list[str] = []

        fetchers = {
            'newsdata':   lambda: _fetch_newsdata(filters, keys['newsdata']),
            'newsapi':    lambda: _fetch_newsapi(filters, keys['newsapi']),
            'gnews':      lambda: _fetch_gnews(filters, keys['gnews']),
            'currents':   lambda: _fetch_currents(filters, keys['currents']),
            'thenewsapi': lambda: _fetch_thenewsapi(filters, keys['thenewsapi']),
            'rss':        lambda: _fetch_rss(filters),
        }

        _src_lock    = _threading.Lock()
        _src_results : dict[str, list] = {}

        def _run_source(name, fn):
            try:
                res = fn()
                with _src_lock:
                    _src_results[name] = res or []
            except Exception as exc:
                logger.error('Source %s raised exception: %s', name, exc)
                with _src_lock:
                    _src_results[name] = []

        _src_threads = [
            _threading.Thread(target=_run_source, args=(n, fn), daemon=True)
            for n, fn in fetchers.items()
        ]
        try:
            for t in _src_threads:
                t.start()
            for t in _src_threads:
                t.join(timeout=25)
        except RuntimeError:
            # Python 3.14: interpreter shutting down during dev-server reload.
            # Fall back to sequential so the request still completes.
            for n, fn in fetchers.items():
                _run_source(n, fn)

        for name, results in _src_results.items():
            if results:
                all_articles.extend(results)
                sources_used.append(NewsAggregatorService.SOURCE_LABELS[name])

        # Merge, deduplicate, sort
        all_articles = _deduplicate(all_articles)

        # Sort: unseen first (newest-first within each group)
        all_articles.sort(key=lambda a: a.get('published_at') or '', reverse=True)
        if seen_urls:
            all_articles = _sort_by_freshness(all_articles, seen_urls)

        total = len(all_articles)
        start = (page - 1) * page_size
        page_articles = all_articles[start:start + page_size]

        has_keys = any(keys.values())
        result = {
            'articles': page_articles,
            'total': total,
            'page': page,
            'has_more': (start + page_size) < total,
            'error': None if all_articles else (
                'No news sources returned articles. Check your API keys or internet connection.'
                if has_keys else
                'No API keys configured — RSS-only mode. Add keys in .env for many more articles.'
            ),
            'sources_used': sources_used,
        }

        if all_articles:
            cache.set(cache_key, result, ttl)
        return result

    @staticmethod
    def get_trending(country: str = 'ke', limit: int = 8) -> list[dict]:
        cache_key = f'news:v2:trending:{country}'
        ttl = getattr(settings, 'NEWS_CACHE_TTL', 180)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        keys = _resolve_keys()
        filters = {'country': country, 'category': 'top', 'language': 'en'}

        articles = _fetch_newsdata(filters, keys['newsdata'], max_pages=1)
        if not articles:
            articles = _fetch_newsapi(filters, keys['newsapi'])
        if not articles:
            articles = _fetch_rss(filters)

        articles = _deduplicate(articles)[:limit]
        if articles:
            cache.set(cache_key, articles, ttl)
        return articles
