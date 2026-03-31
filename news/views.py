import json
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.conf import settings

from .models import SavedArticle
from .services import (
    NewsAggregatorService,
    ALL_CATEGORIES, CONTINENTS, POPULAR_COUNTRIES, SORT_OPTIONS,
)

QUICK_TOPICS = ['politics', 'business', 'technology', 'sports', 'health',
                'entertainment', 'science', 'world']


# ── Helpers ───────────────────────────────────────────────────────────────────
def _get_filter_params(request):
    return {
        'q':         request.GET.get('q', '').strip(),
        'country':   request.GET.get('country', '').strip(),
        'continent': request.GET.get('continent', '').strip(),
        'category':  request.GET.get('category', '').strip(),
        'language':  request.GET.get('language', 'en').strip(),
        'from_date': request.GET.get('from_date', '').strip(),
        'to_date':   request.GET.get('to_date', '').strip(),
        'sort_by':   request.GET.get('sort_by', 'publishedAt').strip(),
        'page':      max(1, int(request.GET.get('page', 1) or 1)),
    }


def _user_key(request) -> str:
    """Unique cache-namespace per authenticated user or per browser session."""
    if request.user.is_authenticated:
        return f'u{request.user.id}'
    if not request.session.session_key:
        request.session.create()
    return f's{request.session.session_key}'


def _get_seen_urls(request) -> set:
    return set(request.session.get('seen_article_urls', []))


def _mark_seen(request, articles: list):
    """Add displayed article URLs to the session so fresh articles appear first."""
    seen = set(request.session.get('seen_article_urls', []))
    seen.update(a['url'] for a in articles if a.get('url'))
    # Cap at 500 to prevent session bloat
    request.session['seen_article_urls'] = list(seen)[-500:]
    request.session.modified = True


def _clear_seen(request):
    """Reset seen-articles history (called on explicit filter clear)."""
    request.session['seen_article_urls'] = []
    request.session.modified = True


def _get_user_defaults(request):
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        p = request.user.profile
        return {
            'default_country':    p.default_country or 'ke',
            'default_categories': p.get_categories_list(),
        }
    return {'default_country': 'ke', 'default_categories': []}


def _saved_states(request, articles: list) -> dict:
    """Return {url: {liked, bookmarked}} for all articles visible to this user."""
    if not request.user.is_authenticated or not articles:
        return {}
    urls = [a['url'] for a in articles if a.get('url')]
    qs   = SavedArticle.objects.filter(
        user=request.user, url__in=urls
    ).values('url', 'interaction_type')
    states: dict = {}
    for row in qs:
        states.setdefault(row['url'], {'liked': False, 'bookmarked': False})
        if row['interaction_type'] == SavedArticle.LIKE:
            states[row['url']]['liked'] = True
        else:
            states[row['url']]['bookmarked'] = True
    return states


def _enrich(articles: list, saved: dict) -> list:
    """Attach saved-state flags to each article dict."""
    for a in articles:
        state = saved.get(a.get('url', ''), {})
        a['liked']      = state.get('liked', False)
        a['bookmarked'] = state.get('bookmarked', False)
    return articles


def _base_context(request, params, result):
    saved = _saved_states(request, result['articles'])
    _enrich(result['articles'], saved)
    _mark_seen(request, result['articles'])
    return {
        'articles':     result['articles'],
        'total':        result['total'],
        'has_more':     result['has_more'],
        'current_page': result['page'],
        'error':        result['error'],
        'sources_used': result['sources_used'],
        'filters':      params,
        'categories':   ALL_CATEGORIES,
        'continents':   CONTINENTS,
        'countries':    POPULAR_COUNTRIES,
        'sort_options': SORT_OPTIONS,
        'quick_topics': QUICK_TOPICS,
        'auto_refresh': settings.NEWS_AUTO_REFRESH,
    }


# ── Views ─────────────────────────────────────────────────────────────────────
def home(request):
    params   = _get_filter_params(request)
    defaults = _get_user_defaults(request)

    # Apply default country only when no geo/search filter is set
    if not params['country'] and not params['continent'] and not params['q']:
        params['country'] = defaults['default_country']

    result = NewsAggregatorService.get_news(
        **{k: v for k, v in params.items()},
        user_key=_user_key(request),
        seen_urls=_get_seen_urls(request),
    )
    trending = NewsAggregatorService.get_trending(
        country=params.get('country') or 'ke'
    )

    ctx = _base_context(request, params, result)
    ctx['trending']   = trending
    ctx['is_my_feed'] = False
    return render(request, 'news/home.html', ctx)


@require_http_methods(['GET'])
def news_feed(request):
    """HTMX partial endpoint — returns feed HTML fragment."""
    params = _get_filter_params(request)

    # _force=1 sent by the manual Refresh button → bypass cache
    force_refresh = request.GET.get('_force') == '1'

    result = NewsAggregatorService.get_news(
        **{k: v for k, v in params.items()},
        user_key=_user_key(request),
        seen_urls=_get_seen_urls(request),
        force_refresh=force_refresh,
    )

    saved = _saved_states(request, result['articles'])
    _enrich(result['articles'], saved)
    _mark_seen(request, result['articles'])

    ctx = {
        'articles':     result['articles'],
        'has_more':     result['has_more'],
        'current_page': result['page'],
        'error':        result['error'],
        'filters':      params,
    }

    if request.htmx:
        if params['page'] > 1:
            # "Load more" appends to the existing grid
            return render(request, 'news/partials/article_list.html', ctx)
        return render(request, 'news/partials/feed_container.html', ctx)

    # Non-HTMX fallback — redirect to homepage with same params
    return redirect('/')


@require_http_methods(['GET'])
def trending(request):
    country  = request.GET.get('country', 'ke')
    articles = NewsAggregatorService.get_trending(country=country)
    return render(request, 'news/partials/trending.html', {'trending': articles})


@login_required
def my_feed(request):
    params  = _get_filter_params(request)
    profile = request.user.profile

    if not params['country']:
        params['country'] = profile.default_country
    if not params['category'] and profile.get_categories_list():
        params['category'] = profile.get_categories_list()[0]

    result = NewsAggregatorService.get_news(
        **{k: v for k, v in params.items()},
        user_key=_user_key(request),
        seen_urls=_get_seen_urls(request),
    )
    ctx = _base_context(request, params, result)
    ctx['trending']   = NewsAggregatorService.get_trending(
        country=params.get('country') or 'ke'
    )
    ctx['is_my_feed'] = True
    return render(request, 'news/home.html', ctx)


@login_required
@require_http_methods(['POST'])
def toggle_interaction(request):
    """Toggle like or bookmark for an article. Works via HTMX or plain form POST."""
    interaction_type = request.POST.get('type', '').strip()
    url          = request.POST.get('url', '').strip()
    title        = request.POST.get('title', '').strip()
    excerpt      = request.POST.get('excerpt', '')
    image_url    = request.POST.get('image_url', '')
    source_name  = request.POST.get('source_name', '')
    published_at = request.POST.get('published_at', '')
    category     = request.POST.get('category', '')

    if not url or interaction_type not in (SavedArticle.LIKE, SavedArticle.BOOKMARK):
        if request.htmx:
            return HttpResponse(status=400)
        return redirect(request.META.get('HTTP_REFERER', '/'))

    obj, created = SavedArticle.objects.get_or_create(
        user=request.user,
        url=url,
        interaction_type=interaction_type,
        defaults=dict(
            title=title, excerpt=excerpt, image_url=image_url,
            source_name=source_name, published_at=published_at, category=category,
        ),
    )
    if not created:
        obj.delete()
        active = False
    else:
        active = True

    # HTMX: return the refreshed button fragment in-place
    if request.htmx:
        return render(request, 'news/partials/interaction_btn.html', {
            'url':              url,
            'title':            title,
            'excerpt':          excerpt,
            'image_url':        image_url,
            'source_name':      source_name,
            'published_at':     published_at,
            'category':         category,
            'interaction_type': interaction_type,
            'active':           active,
        })

    # Plain form POST (e.g. from the dashboard "Remove" button) — redirect back
    messages.success(
        request,
        f'{"Removed from" if not active else "Added to"} {interaction_type}s.',
    )
    return redirect(request.META.get('HTTP_REFERER', '/dashboard/'))


@login_required
def dashboard(request):
    tab         = request.GET.get('tab', 'bookmarks')
    interaction = SavedArticle.BOOKMARK if tab == 'bookmarks' else SavedArticle.LIKE

    saved_articles = SavedArticle.objects.filter(
        user=request.user, interaction_type=interaction
    ).order_by('-saved_at')

    bookmark_count = SavedArticle.objects.filter(
        user=request.user, interaction_type=SavedArticle.BOOKMARK
    ).count()
    like_count = SavedArticle.objects.filter(
        user=request.user, interaction_type=SavedArticle.LIKE
    ).count()

    return render(request, 'news/dashboard.html', {
        'saved_articles': saved_articles,
        'tab':            tab,
        'bookmark_count': bookmark_count,
        'like_count':     like_count,
    })


@login_required
@require_http_methods(['POST'])
def save_preferences(request):
    profile = request.user.profile
    profile.default_country    = request.POST.get('country', 'ke')
    profile.default_categories = request.POST.get('categories', '')
    profile.default_language   = request.POST.get('language', 'en')
    profile.save()
    messages.success(request, 'Preferences saved.')
    if request.htmx:
        return HttpResponse('<div class="text-green-400 text-sm py-1">✓ Saved!</div>')
    return redirect('/')
