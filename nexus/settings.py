"""
Django settings for Epicenter Nexus project.
"""

import os
import tempfile
from pathlib import Path
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Initialize environment variables
env = environ.Env(
    DEBUG=(bool, True),
    ALLOWED_HOSTS=(list, ['localhost', '127.0.0.1']),
)

# Read .env file if it exists
environ.Env.read_env(BASE_DIR / '.env')

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY', default='django-insecure-#x7jfuy-b#qk193mxkov=1%m+5(dmhtop53d_zq1x$nb%cuw!c')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env('DEBUG')

# ALLOWED_HOSTS = env('ALLOWED_HOSTS')

# ALLOWED_HOSTS = [
#     host.strip()
#     for host in os.environ.get("ALLOWED_HOSTS", "").split(",")
#     if host.strip()
# ]
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
    'django_htmx',
    'core',
    'news',
]

# ── SEO / Site identity ────────────────────────────────────────────────────
SITE_NAME        = 'Epicenter Nexus'
SITE_TAGLINE     = 'Real-Time News for Kenya, Africa & the World'
SITE_DESCRIPTION = ('Epicenter Nexus is your live news hub delivering the latest '
                    'breaking news, business, politics, technology, sports and '
                    'more from Kenya, Africa and around the world — updated in real time.')
SITE_URL         = env('SITE_URL', default='https://epicenternexus.com')

INTERNAL_IPS = [
    "127.0.0.1",
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'nexus.middleware.RateLimitMiddleware',       # IP-based rate limiting
    'nexus.middleware.SlowRequestMiddleware',     # log slow requests
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
]

ROOT_URLCONF = 'nexus.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.site_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'nexus.wsgi.application'


# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        'OPTIONS': {
            'timeout': 20,   # seconds to wait for write lock before raising OperationalError
        },
        # Reuse DB connections across requests in the same thread (reduces overhead)
        'CONN_MAX_AGE': env.int('CONN_MAX_AGE', default=60),
    }
}


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True


# Static files
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files (admin-uploaded branding images)
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Caching
# File-based cache stored in the OS temp directory (avoids OneDrive/cloud-sync
# file-locking conflicts).  Shared across all Waitress worker processes on the
# same machine.  Switch to RedisCache for multi-machine deployments.
CACHES = {
    'default': {
        'BACKEND':  'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': os.path.join(tempfile.gettempdir(), 'nexus-cache'),
        'OPTIONS': {
            'MAX_ENTRIES': 5000,
        },
    }
}

# ── Logging ───────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} [{levelname}] {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(BASE_DIR / 'logs' / 'nexus.log'),
            'maxBytes': 10 * 1024 * 1024,   # 10 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'nexus.requests': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'file'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

# Authentication
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# News API Keys (set in .env — all optional, RSS feeds work without any)
NEWSDATA_API_KEY = env('NEWSDATA_API_KEY', default='')
NEWSAPI_KEY = env('NEWSAPI_KEY', default='')
GNEWS_API_KEY = env('GNEWS_API_KEY', default='')
CURRENTS_API_KEY = env('CURRENTS_API_KEY', default='')
THENEWSAPI_KEY = env('THENEWSAPI_KEY', default='')

# News aggregation settings
NEWS_CACHE_TTL = env.int('NEWS_CACHE_TTL', default=180)   # seconds
NEWS_AUTO_REFRESH = env.int('NEWS_AUTO_REFRESH', default=180)  # seconds
NEWS_PAGE_SIZE = env.int('NEWS_PAGE_SIZE', default=12)
