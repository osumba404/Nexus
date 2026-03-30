from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.conf import settings

from .services import (
    NewsAggregatorService,
    ALL_CATEGORIES,
    CONTINENTS,
    POPULAR_COUNTRIES,
    SORT_OPTIONS,
)

QUICK_TOPICS = ['politics', 'business', 'technology', 'sports', 'health', 'entertainment', 'science', 'world']


def _get_filter_params(request):
    """Extract and sanitize filter parameters from GET request."""
    return {
        'q': request.GET.get('q', '').strip(),
        'country': request.GET.get('country', '').strip(),
        'continent': request.GET.get('continent', '').strip(),
        'category': request.GET.get('category', '').strip(),
        'language': request.GET.get('language', 'en').strip(),
        'from_date': request.GET.get('from_date', '').strip(),
        'to_date': request.GET.get('to_date', '').strip(),
        'sort_by': request.GET.get('sort_by', 'publishedAt').strip(),
        'page': max(1, int(request.GET.get('page', 1) or 1)),
    }


def _get_user_defaults(request):
    """Return user's saved default filters if logged in."""
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        profile = request.user.profile
        return {
            'default_country': profile.default_country or 'ke',
            'default_categories': profile.get_categories_list(),
        }
    return {'default_country': 'ke', 'default_categories': []}


def home(request):
    """Main homepage — initial page load with full layout."""
    params = _get_filter_params(request)
    user_defaults = _get_user_defaults(request)

    # Apply user defaults if no explicit filter provided
    if not params['country'] and not params['continent']:
        params['country'] = user_defaults['default_country']

    result = NewsAggregatorService.get_news(**{k: v for k, v in params.items()})
    trending = NewsAggregatorService.get_trending(country=params.get('country') or 'ke')

    context = {
        'articles': result['articles'],
        'total': result['total'],
        'has_more': result['has_more'],
        'current_page': result['page'],
        'error': result['error'],
        'sources_used': result['sources_used'],
        'filters': params,
        'trending': trending,
        # Filter options
        'categories': ALL_CATEGORIES,
        'continents': CONTINENTS,
        'countries': POPULAR_COUNTRIES,
        'sort_options': SORT_OPTIONS,
        'quick_topics': QUICK_TOPICS,
        # Settings
        'auto_refresh': settings.NEWS_AUTO_REFRESH,
    }
    return render(request, 'news/home.html', context)


@require_http_methods(['GET'])
def news_feed(request):
    """
    HTMX endpoint — returns only the news feed partial (cards).
    Used for filter changes, infinite scroll and auto-refresh.
    """
    params = _get_filter_params(request)
    result = NewsAggregatorService.get_news(**{k: v for k, v in params.items()})

    context = {
        'articles': result['articles'],
        'has_more': result['has_more'],
        'current_page': result['page'],
        'error': result['error'],
        'filters': params,
    }

    if request.htmx:
        # "load more" — append to existing list
        if params['page'] > 1:
            return render(request, 'news/partials/article_list.html', context)
        # Filter change — swap the whole feed container
        return render(request, 'news/partials/feed_container.html', context)

    # Non-HTMX fallback: redirect to home with same params
    return redirect('/')


@require_http_methods(['GET'])
def trending(request):
    """HTMX endpoint — returns trending sidebar articles."""
    country = request.GET.get('country', 'ke')
    articles = NewsAggregatorService.get_trending(country=country)
    return render(request, 'news/partials/trending.html', {'trending': articles})


@login_required
def my_feed(request):
    """Personalized feed based on saved preferences."""
    profile = request.user.profile
    params = _get_filter_params(request)

    # Override with profile defaults
    if not params['country']:
        params['country'] = profile.default_country
    if not params['category'] and profile.default_categories:
        params['category'] = profile.get_categories_list()[0] if profile.get_categories_list() else ''

    result = NewsAggregatorService.get_news(**{k: v for k, v in params.items()})

    context = {
        'articles': result['articles'],
        'total': result['total'],
        'has_more': result['has_more'],
        'current_page': result['page'],
        'error': result['error'],
        'sources_used': result['sources_used'],
        'filters': params,
        'categories': ALL_CATEGORIES,
        'continents': CONTINENTS,
        'countries': POPULAR_COUNTRIES,
        'sort_options': SORT_OPTIONS,
        'quick_topics': QUICK_TOPICS,
        'auto_refresh': settings.NEWS_AUTO_REFRESH,
        'is_my_feed': True,
    }
    return render(request, 'news/home.html', context)


@login_required
@require_http_methods(['POST'])
def save_preferences(request):
    """Save user filter preferences to their profile."""
    profile = request.user.profile
    profile.default_country = request.POST.get('country', 'ke')
    profile.default_categories = request.POST.get('categories', '')
    profile.default_language = request.POST.get('language', 'en')
    profile.save()
    messages.success(request, 'Preferences saved successfully.')

    if request.htmx:
        return HttpResponse('<div class="text-green-400 text-sm">Saved!</div>')
    return redirect('/')
