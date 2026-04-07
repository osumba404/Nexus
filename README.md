# Epicenter Nexus

**Real-Time News for Kenya, Africa & the World**

A full-stack Django news aggregation platform that pulls live articles from multiple sources, lets users filter by country, category, and language, and delivers a clean reading experience with full article content, comments, likes, and bookmarks.

---

## Features

- **Multi-source aggregation** — pulls from NewsData.io, NewsAPI, GNews, Currents, TheNewsAPI, and RSS feeds simultaneously
- **Smart deduplication** — articles seen across sources are merged and ranked; already-seen URLs surface last
- **Full article reader** — scrapes and renders the complete article body directly in the app (no paywall bypass — falls back gracefully)
- **Article interactions** — like and bookmark articles; manage saved articles from a personal dashboard
- **Comments** — authenticated users can post and delete comments on any article
- **Trending sidebar** — top headlines for the selected country, auto-refreshed
- **My Feed** — personalised feed based on preferred country and categories saved to the user profile
- **HTMX-powered** — article loading, interactions, comments, and feed refresh all work without full page reloads
- **Light / Dark theme** — system-aware with manual toggle, persisted across sessions
- **Share articles** — copy a deep link to the internal article detail page
- **SEO-ready** — sitemap, Open Graph meta tags, canonical URLs, and structured `<title>` tags

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 6.0 |
| Real-time UI | HTMX 1.x + django-htmx |
| Styling | Tailwind CSS (CDN) + custom `nexus.css` |
| Database | SQLite (development) |
| Content extraction | trafilatura + lxml |
| Feed parsing | feedparser |
| HTTP client | requests |
| Environment | django-environ |

---

## Project Structure

```
Nexus/
├── core/               # User profiles, authentication, context processors
├── news/               # News aggregation app
│   ├── models.py       # SavedArticle, ArticleComment
│   ├── services.py     # Aggregation logic, RSS fetching, article scraper
│   ├── views.py        # Feed, article detail, interactions, dashboard
│   └── urls.py
├── nexus/              # Django project config (settings, urls, wsgi)
├── templates/
│   ├── base.html
│   └── news/
│       ├── home.html
│       ├── article_detail.html
│       ├── dashboard.html
│       └── partials/   # HTMX partials (feed, article content, buttons, comments)
├── static/
│   └── css/nexus.css   # Design system tokens + component styles
├── requirements.txt
└── .env                # API keys and overrides (not committed)
```

---

## Installation

### 1. Clone the repository

```bash
git clone <repo-url>
cd Nexus
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `trafilatura` and `lxml` are required for the full article reader but are not in `requirements.txt` — install them separately:
> ```bash
> pip install trafilatura lxml
> ```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# News API keys — all optional; RSS feeds work without any
NEWSDATA_API_KEY=
NEWSAPI_KEY=
GNEWS_API_KEY=
CURRENTS_API_KEY=
THENEWSAPI_KEY=

# Optional overrides
NEWS_CACHE_TTL=180
NEWS_AUTO_REFRESH=180
NEWS_PAGE_SIZE=12
SITE_URL=http://localhost:8080
```

At least one API key is recommended for a better article volume; the app works with RSS-only but will return fewer results.

### 5. Apply migrations

```bash
python manage.py migrate
```

### 6. Create a superuser (optional)

```bash
python manage.py createsuperuser
```

### 7. Run the development server

```bash
python manage.py runserver 8080
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080).

---

## API Keys

| Provider | Where to get it | Environment variable |
|---|---|---|
| NewsData.io | newsdata.io/register | `NEWSDATA_API_KEY` |
| NewsAPI | newsapi.org/register | `NEWSAPI_KEY` |
| GNews | gnews.io | `GNEWS_API_KEY` |
| Currents API | currentsapi.services | `CURRENTS_API_KEY` |
| TheNewsAPI | thenewsapi.com | `THENEWSAPI_KEY` |

All keys are optional. Configure as many or as few as you like.

---

## Key URLs

| URL | Description |
|---|---|
| `/` | Main news feed |
| `/my-feed/` | Personalised feed (login required) |
| `/article/?url=...` | Full article detail page |
| `/dashboard/` | Saved articles and likes |
| `/accounts/login/` | Login |
| `/accounts/register/` | Register |
| `/admin/` | Django admin |

---

## Settings Reference

All settings can be overridden via `.env`:

| Setting | Default | Description |
|---|---|---|
| `NEWS_CACHE_TTL` | `180` | Seconds to cache fetched articles |
| `NEWS_AUTO_REFRESH` | `180` | Client-side auto-refresh interval (seconds) |
| `NEWS_PAGE_SIZE` | `12` | Articles per page |
| `DEBUG` | `True` | Django debug mode |
| `TIME_ZONE` | `Africa/Nairobi` | Server timezone (in `settings.py`) |

---

## Development Notes

- The article scraper (`fetch_article_content`) uses `trafilatura` with a 10-second timeout and caches results in Django's in-memory cache for 2 hours. Paywalled or JS-heavy articles will show a "Full text unavailable" message with a link to the source.
- The feed uses session-based deduplication — articles you've already seen are pushed to the end on subsequent loads. Clear your session or use incognito to reset.
- The dev server uses `threading.Thread` (not `ThreadPoolExecutor`) for parallel source fetching to avoid Python 3.14 interpreter-shutdown errors.

---

## License

MIT — see `LICENSE` for details.

---

*Built by 404Evans™*
