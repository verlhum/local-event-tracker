# Local Event Tracker

A Django-based admin tool for scraping, reviewing, managing, and exporting local dance and live music event listings.

I built this as a spare-time project to reduce the manual work involved in creating weekly event lists. The tool combines scraped events, manual one-off events, recurring events, review statuses, override workflows, and export tools into one Django Admin interface.

This is not intended to be a polished public SaaS app. It is a practical workflow automation project built around a real recurring use case: collecting candidate events, reviewing them, correcting details, handling recurring listings, and producing weekly event exports.

## What It Does

Local Event Tracker helps manage weekly event listings by combining three event sources:

- **Scraped events** from configured source pages
- **Manual single events** for one-off listings
- **Manual recurring events** for repeated weekly or monthly events

The admin workflow is designed around reviewing candidate events, cleaning up details, hiding duplicates or irrelevant listings, and exporting a usable weekly event list.

## Features

- Django Admin-based event management
- Scraped event import and review workflow
- Manual one-off event entry
- Manual recurring event rules
- Recurring event exceptions and overrides
- Admin actions for marking events approved, hidden, canceled, duplicate, or irrelevant
- Batch editing for scraped events
- Current-week date filtering on scraped event review
- “Save and add similar” workflow for faster manual event entry
- Weekly export views for full-week, weekday, and weekend-style posts
- Plain-text event formatting for copying into posts
- Optional image export for social media-style weekly event graphics

## Tech Stack

- Python
- Django
- SQLite
- Django Admin customization
- HTML templates
- Pillow for image export
- BeautifulSoup / Requests for scraping
- Optional Playwright support for JavaScript-rendered pages

## Project Scope

This project is intentionally local and workflow-specific. Several scraper rules are tailored to local Reno/Sparks/Carson City dance and live music sources. The goal was not to build a universal event platform, but to automate a real curation process that had become repetitive.

Some parts of the scraper contain source-specific logic because venue websites and event calendars often publish inconsistent or semi-structured data.

## Setup

Clone the repository:

```bash
git clone <repo-url>
cd <repo-folder>
```

Create and activate a virtual environment:

```bash
python -m venv .venv
```

On Windows:

```bash
.venv\Scripts\activate
```

On macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run migrations:

```bash
python manage.py migrate
```

Create an admin user:

```bash
python manage.py createsuperuser
```

Start the development server:

```bash
python manage.py runserver
```

Open the Django Admin:

```text
http://127.0.0.1:8000/admin/
```

## Configuration Notes

This project uses local development settings by default.

Before publishing or deploying, make sure the following are not committed:

- `.env`
- `db.sqlite3`
- local media files
- generated event images
- virtual environment folders
- logs
- private source data

Image export uses local assets and font fallbacks. On non-Windows systems, you may need to install fonts or adjust the font paths in `image_export.py`.

Expected local asset examples:

```text
assets/
├── wood_background.jpg
├── swingin_country_logo.png
└── fonts/
```

## Useful Admin Views

The project includes custom admin views for:

```text
/admin/events/export/
/admin/events/scrape/
```

The standard Django Admin remains the main interface for creating, reviewing, correcting, and exporting event data.

## Data Model Overview

The core models include:

- `ManualSingleEvent` — manually entered one-off events
- `ManualRecurringEvent` — recurring event rules
- `RecurringException` — cancellations or overrides for recurring events
- `ScrapedEvent` — imported candidate events from scraper sources
- `ScrapedEventOverride` — manual corrections or review decisions for scraped events
- `ScrapeSource` — configured sources to scrape
- `ScrapeRun` — scrape/import run history
- `EventLog` — simple audit log for manual changes

## Why I Built This

I regularly create weekly local dance and live music event lists. Manually checking sources, copying event details, filtering irrelevant events, correcting venue information, and formatting the final list took too much repeated effort.

This project gave me a way to turn that recurring process into a structured workflow:

1. Pull in candidate events.
2. Review and correct them.
3. Add manual events when needed.
4. Handle recurring events and exceptions.
5. Export a clean weekly list or image.

## Future Improvements

Possible next improvements include:

- Better scraper test coverage
- More structured source configuration
- Improved duplicate detection
- More flexible export templates
- Better image template customization
- Deployment-ready settings split
- More complete documentation for adding new event sources

## Status

This is an active personal side project. It is shared as an example of practical workflow automation using Django, not as a finished commercial product.
