from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, date, timezone as dt_timezone
from html import unescape
from typing import Any, Callable, Optional
from urllib.parse import quote, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from dateutil.rrule import rrulestr

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False
    
from zoneinfo import ZoneInfo


# =========================================================
# Config
# =========================================================

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT = 30
WINDOW_DAYS_PAST = 7
WINDOW_DAYS_FUTURE = 14
MAX_DESCRIPTION_LEN = 200
MAX_SUMMARY_LEN = 120

EXCLUDE_TITLE_PATTERNS = [
    r"(?i)^now open\b",
    r"(?i)\bopen 7 days\b",
    r"(?i)\bgame room\b",
    r"(?i)^hours$",
    r"(?i)^business hours$",
    r"(?i)\bbluegrass.*jam\b",
    r"(?i)\bsongwriter'?s night\b",
    r"(?i)\btrivia\b",
    r"(?i)\bkaraoke\b",
    r"(?i)\bkids crafts\b",
    r"(?i)\bbingo\b",
    r"(?i)\bopen mic\b",
]

RELEVANT_CATEGORY_PATTERNS = [
    r"(?i)music",
    r"(?i)dancing?",
    r"(?i)concert",
    r"(?i)band",
    r"(?i)party",
    r"(?i)latin",
    r"(?i)salsa",
    r"(?i)bachata",
    r"(?i)swing",
]

TARGET_CITY_PATTERNS = [
    r"(?i)\breno\b",
    r"(?i)\bsparks\b",
    r"(?i)\bcarson city\b",
]

OUT_OF_SCOPE_LOCATION_PATTERNS = [
    r"(?i)\bstateline\b",
    r"(?i)\blake tahoe\b",
    r"(?i)\bsouth lake tahoe\b",
    r"(?i)\btahoe\b",
    r"(?i)\bminden\b",
    r"(?i)\bgardnerville\b",
]

KNOWN_LOCAL_VENUE_PATTERNS = [
    r"(?i)\bzephyr wine bar\b",
    r"(?i)\bmax casino\b",
    r"(?i)\bcasino fandango\b",
    r"(?i)\bneed 2 speed\b",
    r"(?i)\bsouth 40\b",
    r"(?i)\bpolecat tavern\b",
    r"(?i)\bmidtown spirits\b",
    r"(?i)\breno public market\b",
    r"(?i)\bpure country canteen\b",
    r"(?i)\bballroom of reno\b",
]

PERFORMER_CALENDAR_SOURCES = [
    "https://recklessenvy.com/calendar-2/",
    "https://www.rickhays.com/event",
]

MONTH_NAME_TO_NUM = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

DAY_NAME_PATTERN = r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
TIME_PATTERN = r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")


# =========================================================
# Public result shape
# =========================================================

@dataclass
class ScrapeResult:
    success: bool
    input_url: str
    normalized_url: str | None
    platform: str | None
    method: str | None
    events: list[dict[str, Any]]
    metadata: dict[str, Any]
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "input_url": self.input_url,
            "normalized_url": self.normalized_url,
            "platform": self.platform,
            "method": self.method,
            "events": self.events,
            "metadata": self.metadata,
            "error": self.error,
        }


# =========================================================
# Core helpers
# =========================================================

def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def window_start_end() -> tuple[datetime, datetime]:
    now = now_local()
    return now - timedelta(days=WINDOW_DAYS_PAST), now + timedelta(days=WINDOW_DAYS_FUTURE)


def normalize_url(url: str) -> str:
    if not isinstance(url, str):
        raise ValueError("URL must be a string.")
    url = url.strip()
    if not url:
        raise ValueError("URL is empty.")
    url = url.replace("\\", "/")
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    if not parsed.netloc:
        raise ValueError(f"URL is missing a valid domain: {url}")
    if parsed.scheme.lower() == "http":
        url = parsed._replace(scheme="https").geturl()
    return url


def request_text(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def request_json(url: str, params: Optional[dict] = None) -> dict:
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, params=params)
    response.raise_for_status()
    return response.json()


def normalize_text(text: Any) -> str:
    if text is None:
        return ""
    text = str(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def trim_text(text: str, max_len: int) -> str:
    text = normalize_text(text)
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    trimmed = text[:max_len].rsplit(" ", 1)[0].strip()
    return trimmed + "…"


def clean_title(title: Any) -> str:
    return normalize_text(title).strip(" -—")


def clean_location_piece(value: Any) -> str:
    return normalize_text(value).strip(" ,-") or ""


def clean_description(value: Any) -> str:
    return trim_text(normalize_text(value), MAX_DESCRIPTION_LEN)


def categories_to_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [normalize_text(v) for v in value if normalize_text(v)]
    cleaned = normalize_text(value)
    return [cleaned] if cleaned else []


def _safe_parse_dt_any(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value

    value = str(value).strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        pass

    try:
        dt = parse_ics_datetime(value)
        if dt:
            return dt
    except Exception:
        pass

    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M %p",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except Exception:
            continue
    return None


def _ensure_iso_datetime(value: Any, tzinfo=None) -> str | None:
    dt = _safe_parse_dt_any(value)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tzinfo or now_local().tzinfo)
    return dt.isoformat(timespec="seconds")


def parse_time_to_24h(text: str) -> Optional[tuple[int, int]]:
    match = re.search(TIME_PATTERN, text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = match.group(3).lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    return hour, minute


def next_weekday(base_dt: datetime, target_weekday: int) -> datetime:
    days_ahead = (target_weekday - base_dt.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base_dt + timedelta(days=days_ahead)

def looks_like_music_title(text: str) -> bool:
    if not text:
        return False

    lower = text.lower()

    music_patterns = [
        r"\blive\b",
        r"\bmusic\b",
        r"\bband\b",
        r"\bduo\b",
        r"\btrio\b",
        r"\bsolo\b",
        r"\bsinger\b",
        r"\bartist\b",
        r"\bacoustic\b",
        r"\bfeat\b",
        r"\bfeaturing\b",
        r"\bwith\b",
        r"\bjam\b",
        r"\bopen mic\b",
        r"\bkaraoke\b",
        r"\bdj\b",
    ]

    return any(re.search(pattern, lower) for pattern in music_patterns)

def _clean_zephyr_artist_title(title: str) -> str:
    """
    Remove trailing embedded date text from a Zephyr artist title.
    Example:
      'The Road Apples April 6th, Monday' -> 'The Road Apples'
    """
    text = normalize_text(title)

    text = re.sub(
        r"\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday))?$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    return text

def _is_zephyr_intro_line(text: str) -> bool:
    lower = normalize_text(text).lower()
    bad_patterns = [
        r"acts range from",
        r"relax on sunday",
        r"line[\s\-]*up",
        r"weekly events at zephyr",
        r"live music every sunday",
        r"mondays and tuesdays",
        r"first fridays",
        r"announcing even more live music",
    ]
    return any(re.search(pattern, lower) for pattern in bad_patterns)


def _is_zephyr_bad_title(text: str) -> bool:
    lower = normalize_text(text).lower()
    bad_patterns = [
        r"\bannouncing\b",
        r"\beven more live music\b",
    ]
    return any(re.search(pattern, lower) for pattern in bad_patterns)


def _extract_zephyr_dated_artist_lines(text: str, now_dt: datetime, visible_year: int) -> list[dict]:
    events = []

    lines = [normalize_text(x) for x in text.splitlines() if normalize_text(x)]

    pattern = re.compile(
        r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2})(?:st|nd|rd|th)?,\s*"
        r"(Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday)\s*[–-]\s*(.+)$",
        re.IGNORECASE,
    )

    for line in lines:
        match = pattern.match(line)
        if not match:
            continue

        month_name, day, weekday, artist = match.groups()
        artist = artist.strip()

        if _is_zephyr_intro_line(line):
            continue
        if _is_zephyr_bad_title(artist):
            continue

        month = MONTH_NAME_TO_NUM[month_name.lower()]
        day = int(day)
        weekday_lower = weekday.lower()

        if weekday_lower == "sunday":
            start_hour, start_minute = 15, 0
            end_hour, end_minute = 18, 0
        elif weekday_lower in {"monday", "tuesday"}:
            start_hour, start_minute = 17, 30
            end_hour, end_minute = 19, 30
        else:
            continue

        try:
            start_dt = datetime(visible_year, month, day, start_hour, start_minute, tzinfo=LOCAL_TZ)
            end_dt = datetime(visible_year, month, day, end_hour, end_minute, tzinfo=LOCAL_TZ)
        except Exception:
            continue

        events.append({
            "title": artist,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "description": f"{weekday} live music at Zephyr Wine Bar.",
            "location": "Zephyr Wine Bar",
            "venue": "Zephyr Wine Bar",
            "city": "Reno",
            "state": "NV",
            "categories": ["Music", "Live Music"],
        })

    return events

def _parse_zephyr_artist_and_time(text: str) -> tuple[str, Optional[tuple[int, int]], Optional[tuple[int, int]]]:
    """
    Parses:
      Brad the Guitarist (5-7pm)
      Tyler John Kraehling (6-8pm)
      Joaquin Fioresi Duo (3-6pm)
      Some Artist (5:30-7:30pm)

    Returns:
      clean_title, start_time, end_time
    """
    text = normalize_text(text)

    match = re.search(
        r"\((\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*[–-]\s*"
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\)",
        text,
        re.IGNORECASE,
    )

    if not match:
        return text, None, None

    start_hour = int(match.group(1))
    start_minute = int(match.group(2) or 0)
    start_ampm = match.group(3)
    end_hour = int(match.group(4))
    end_minute = int(match.group(5) or 0)
    end_ampm = match.group(6).lower()

    # If start AM/PM is omitted, infer from end AM/PM.
    start_ampm = (start_ampm or end_ampm).lower()

    if start_ampm == "pm" and start_hour != 12:
        start_hour += 12
    if start_ampm == "am" and start_hour == 12:
        start_hour = 0

    if end_ampm == "pm" and end_hour != 12:
        end_hour += 12
    if end_ampm == "am" and end_hour == 12:
        end_hour = 0

    title = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()

    return title, (start_hour, start_minute), (end_hour, end_minute)

def _is_excluded_calendar_format(event: dict[str, Any]) -> bool:
    blob = _event_text_blob(event)

    exclude_patterns = [
        r"(?i)\bkaraoke\b",
        r"(?i)\bopen mic\b",
        r"(?i)\bunplugged jam\b",
        r"(?i)\bacoustic jam\b",
        r"(?i)\bjam session\b",
        r"(?i)\bnetworking\b",
        r"(?i)\bmeet & greet\b",
        r"(?i)\bcanyon club\b",
        r"(?i)\bsongwriter'?s night\b",
    ]

    return _matches_any_pattern(blob, exclude_patterns)

def fetch_page_html_with_playwright(url: str) -> str:
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError(
            "Playwright is not installed. Install it with `pip install playwright` "
            "and run `playwright install chromium`."
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="load", timeout=60000)
        page.wait_for_timeout(4000)
        html = page.content()
        browser.close()

    return html

# =========================================================
# Relevance / filtering
# =========================================================

def _title_contains_venue(title: str, venue: str) -> bool:
    if not title or not venue:
        return False
    t = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    v = re.sub(r"[^a-z0-9]+", " ", venue.lower()).strip()
    return bool(v and v in t)


def build_event_summary(event: dict[str, Any], max_len: int = MAX_SUMMARY_LEN) -> str:
    title = clean_title(event.get("title"))
    venue = clean_location_piece(event.get("venue"))
    city = clean_location_piece(event.get("city"))
    state = clean_location_piece(event.get("state"))
    categories = categories_to_list(event.get("categories"))

    parts: list[str] = []
    if title:
        parts.append(title)

    place = ""
    if venue and city:
        place = f"at {venue} — {city}"
    elif venue and state:
        place = f"at {venue} — {state}"
    elif venue:
        place = f"at {venue}"
    elif city and state:
        place = f"in {city}, {state}"
    elif city:
        place = f"in {city}"

    if venue and _title_contains_venue(title, venue):
        if city:
            place = f"— {city}"
        elif state:
            place = f"— {state}"
        else:
            place = ""

    if place:
        parts.append(place)
    if categories:
        parts.append(f"({', '.join(categories[:2])})")

    summary = " ".join(parts).strip()
    summary = re.sub(r"\s+—", " —", summary)
    summary = re.sub(r"\s+", " ", summary).strip()
    return trim_text(summary, max_len)


def _matches_any_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _event_text_blob(event: dict[str, Any]) -> str:
    parts = [
        clean_title(event.get("title")),
        clean_location_piece(event.get("venue")),
        clean_location_piece(event.get("city")),
        clean_location_piece(event.get("state")),
        clean_location_piece(event.get("location")),
        normalize_text(event.get("source_page")),
        normalize_text(event.get("description")),
    ]
    return " | ".join([p for p in parts if p]).lower()


def _is_performer_calendar_event(event: dict[str, Any]) -> bool:
    return normalize_text(event.get("source_page")) in PERFORMER_CALENDAR_SOURCES


def _is_out_of_scope_event(event: dict[str, Any]) -> bool:
    return _matches_any_pattern(_event_text_blob(event), OUT_OF_SCOPE_LOCATION_PATTERNS)


def _is_target_area_event(event: dict[str, Any]) -> bool:
    blob = _event_text_blob(event)
    return _matches_any_pattern(blob, TARGET_CITY_PATTERNS) or _matches_any_pattern(blob, KNOWN_LOCAL_VENUE_PATTERNS)


def _is_private_or_unhelpful(event: dict[str, Any]) -> bool:
    return bool(re.search(r"(?i)\bprivate party\b", clean_title(event.get("title"))))


def compute_likely_relevant(event: dict) -> bool:
    title = clean_title(event.get("title"))
    categories = categories_to_list(event.get("categories"))
    category_blob = " ".join(categories)
    blob = _event_text_blob(event)

    if not title or _is_out_of_scope_event(event) or _is_private_or_unhelpful(event):
        return False

    if _is_non_danceable_small_venue(event):
        return False

    if _is_excluded_calendar_format(event):
        return False

    if categories and any(re.search(p, category_blob) for p in RELEVANT_CATEGORY_PATTERNS):
        return True

    content_has_music_signal = (
        _matches_any_pattern(blob, RELEVANT_CATEGORY_PATTERNS)
        or bool(re.search(r"(?i)\blive\b|\bband\b|\bduo\b|\btrio\b|\bdj\b", blob))
    )

    if _is_target_area_event(event) and content_has_music_signal:
        return True

    if _is_performer_calendar_event(event):
        if _matches_any_pattern(blob, KNOWN_LOCAL_VENUE_PATTERNS):
            return True
        if _matches_any_pattern(blob, TARGET_CITY_PATTERNS):
            return True

    return False

def is_relevant_event(event: dict[str, Any]) -> bool:
    title = clean_title(event.get("title"))
    if not title:
        return False
    for pattern in EXCLUDE_TITLE_PATTERNS:
        if re.search(pattern, title):
            return False
    return True

def expand_ics_event_instances(event: dict[str, Any], window_start: datetime, window_end: datetime) -> list[tuple[datetime, Optional[datetime]]]:
    start_raw = event.get("DTSTART")
    end_raw = event.get("DTEND")
    if not start_raw:
        return []

    start_dt = parse_ics_datetime(start_raw)
    end_dt = parse_ics_datetime(end_raw) if end_raw else None
    if not start_dt:
        return []

    local_tz = now_local().tzinfo

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=local_tz)
    else:
        start_dt = start_dt.astimezone(local_tz)

    if end_dt:
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=local_tz)
        else:
            end_dt = end_dt.astimezone(local_tz)

    duration = (end_dt - start_dt) if end_dt else None

    rrule_text = event.get("RRULE")
    exdates = set()

    for ex_raw in event.get("EXDATE", []):
        ex_dt = parse_ics_datetime(ex_raw)
        if ex_dt:
            if ex_dt.tzinfo is None:
                ex_dt = ex_dt.replace(tzinfo=local_tz)
            else:
                ex_dt = ex_dt.astimezone(local_tz)
            exdates.add(ex_dt)

    # Non-recurring event
    if not rrule_text:
        if window_start <= start_dt <= window_end:
            return [(start_dt, start_dt + duration if duration else end_dt)]
        return []

    # Recurring event
    try:
        rule = rrulestr(rrule_text, dtstart=start_dt)
        instances = rule.between(window_start, window_end, inc=True)
    except Exception:
        return []

    output = []
    for inst_start in instances:
        if inst_start in exdates:
            continue
        inst_end = inst_start + duration if duration else None
        output.append((inst_start, inst_end))

    return output

def _is_non_danceable_small_venue(event: dict[str, Any]) -> bool:
    blob = _event_text_blob(event)
    patterns = [
        r"(?i)\btap shack\b",
    ]
    return _matches_any_pattern(blob, patterns)


# =========================================================
# Canonical normalized event shape
# =========================================================

CANONICAL_KEYS = [
    "source_page",
    "source_url",
    "platform",
    "method",
    "raw_source_id",
    "title",
    "start",
    "end",
    "description",
    "location",
    "venue",
    "city",
    "state",
    "event_url",
    "status",
    "all_day",
    "categories",
    "tags",
    "summary",
    "likely_relevant",
    "fingerprint_source",
]


def fingerprint_event_source(event: dict[str, Any]) -> str:
    """
    Stable-ish source fingerprint for preview/debug matching.
    Not a DB primary key, just useful for comparisons across test runs.
    """
    parts = [
        normalize_text(event.get("platform")).lower(),
        normalize_text(event.get("method")).lower(),
        normalize_text(event.get("raw_source_id")).lower(),
        normalize_text(event.get("start")).lower(),
        normalize_text(event.get("event_url")).lower(),
        normalize_text(event.get("venue")).lower(),
        normalize_text(event.get("location")).lower(),
        normalize_text(event.get("title")).lower(),
    ]
    base = "|".join(parts)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def finalize_normalized_event(event: dict[str, Any]) -> dict[str, Any]:
    event = dict(event)

    event["source_page"] = normalize_text(event.get("source_page"))
    event["source_url"] = normalize_text(event.get("source_url")) or None
    event["platform"] = normalize_text(event.get("platform"))
    event["method"] = normalize_text(event.get("method"))
    event["raw_source_id"] = normalize_text(event.get("raw_source_id")) or None

    event["title"] = clean_title(event.get("title"))
    event["start"] = _ensure_iso_datetime(event.get("start"))
    event["end"] = _ensure_iso_datetime(event.get("end"))

    event["description"] = clean_description(event.get("description"))
    event["location"] = clean_location_piece(event.get("location")) or None
    event["venue"] = clean_location_piece(event.get("venue")) or None
    event["city"] = clean_location_piece(event.get("city")) or None
    event["state"] = clean_location_piece(event.get("state")) or None

    event["event_url"] = normalize_text(event.get("event_url")) or None
    event["status"] = normalize_text(event.get("status")) or None
    event["all_day"] = event.get("all_day") if isinstance(event.get("all_day"), bool) else None

    event["categories"] = categories_to_list(event.get("categories"))
    event["tags"] = categories_to_list(event.get("tags"))

    event["summary"] = build_event_summary(event)
    event["likely_relevant"] = compute_likely_relevant(event)
    event["fingerprint_source"] = fingerprint_event_source(event)

    # hard guarantee shape
    normalized = {key: event.get(key) for key in CANONICAL_KEYS}
    return normalized


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    output = []

    for event in events:
        key = (
            clean_title(event.get("title")).lower(),
            normalize_text(event.get("start")),
            clean_location_piece(event.get("venue")).lower(),
            clean_location_piece(event.get("city")).lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(event)

    output.sort(key=lambda e: (e.get("start") or "", e.get("title") or ""))
    return output


def finalize_event_list(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for event in events:
        normalized = finalize_normalized_event(event)
        if not normalized.get("title"):
            continue
        if not normalized.get("start"):
            continue
        if not is_relevant_event(normalized):
            continue
        cleaned.append(normalized)
    return dedupe_events(cleaned)


def _result(
    *,
    success: bool,
    input_url: str,
    normalized_url: str | None,
    platform: str | None,
    method: str | None,
    events: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return ScrapeResult(
        success=success,
        input_url=input_url,
        normalized_url=normalized_url,
        platform=platform,
        method=method,
        events=finalize_event_list(events or []),
        metadata=metadata or {},
        error=error,
    ).as_dict()


# =========================================================
# Google calendar / ICS
# =========================================================

def normalize_google_calendar_id(raw_id: str) -> Optional[str]:
    if not raw_id:
        return None
    value = unquote(raw_id.strip()).replace("&amp;", "&")
    if "&" in value:
        value = value.split("&", 1)[0]
    if "@group.calendar.google.com" in value or "@gmail.com" in value:
        return value
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
        decoded = unquote(decoded)
        if "@group.calendar.google.com" in decoded or "@gmail.com" in decoded:
            return decoded
    except Exception:
        pass
    return value or None


def extract_google_calendar_id_from_html(html: str) -> Optional[str]:
    patterns = [
        r'calendar/embed\?[^"\']*src=([^&"\']+)',
        r'calendar/embed\?[^"\']*src=([^&]+)',
        r'clients\d+\.google\.com/calendar/v3/calendars/([^/"\']+)/events',
    ]
    candidates: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            raw = match.group(1)
            if raw:
                candidates.append(raw)
    for raw in candidates:
        cal_id = normalize_google_calendar_id(raw)
        if cal_id:
            return cal_id
    return None


def parse_ics_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    try:
        if re.fullmatch(r"\d{8}T\d{6}Z", value):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt_timezone.utc)
        if re.fullmatch(r"\d{8}T\d{6}", value):
            return datetime.strptime(value, "%Y%m%dT%H%M%S")
        if re.fullmatch(r"\d{8}", value):
            return datetime.strptime(value, "%Y%m%d")
    except Exception:
        return None
    return None


def unfold_ics_lines(text: str) -> list[str]:
    lines = text.splitlines()
    unfolded: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def parse_ics_events(ics_text: str) -> list[dict[str, Any]]:
    lines = unfold_ics_lines(ics_text)
    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in lines:
        line = line.rstrip()
        if line == "BEGIN:VEVENT":
            current = {"EXDATE": []}
            continue
        if line == "END:VEVENT":
            if current:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue

        key_part, value = line.split(":", 1)
        key_main = key_part.split(";", 1)[0].upper()

        params = {}
        if ";" in key_part:
            for piece in key_part.split(";")[1:]:
                if "=" in piece:
                    p_key, p_val = piece.split("=", 1)
                    params[p_key.upper()] = p_val

        if key_main in {"SUMMARY", "DESCRIPTION", "LOCATION", "UID", "STATUS", "URL", "RRULE"}:
            current[key_main] = value
        elif key_main in {"DTSTART", "DTEND"}:
            current[key_main] = value
            if "TZID" in params:
                current[f"{key_main}_TZID"] = params["TZID"]
        elif key_main == "EXDATE":
            current["EXDATE"].append(value)

    return events


def extract_google_calendar_events_via_ics(source_page: str, calendar_id: str) -> dict[str, Any]:
    start_window, end_window = window_start_end()
    ics_url = f"https://calendar.google.com/calendar/ical/{quote(calendar_id, safe='')}/public/basic.ics"

    response = requests.get(ics_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    raw_events = parse_ics_events(response.text)
    events: list[dict[str, Any]] = []

    for item in raw_events:
        instances = expand_ics_event_instances(item, start_window, end_window)

        for inst_start, inst_end in instances:
            events.append({
                "source_url": ics_url,
                "source_page": source_page,
                "platform": "google_calendar",
                "method": "google_calendar_ics",
                "raw_source_id": item.get("UID"),
                "title": item.get("SUMMARY"),
                "start": inst_start.isoformat(),
                "end": inst_end.isoformat() if inst_end else None,
                "description": item.get("DESCRIPTION"),
                "location": item.get("LOCATION"),
                "venue": None,
                "city": None,
                "state": None,
                "event_url": item.get("URL"),
                "status": item.get("STATUS"),
                "all_day": bool(item.get("DTSTART") and re.fullmatch(r"\d{8}", item["DTSTART"].strip())),
                "categories": [],
                "tags": [],
            })

    return _result(
        success=True,
        input_url=source_page,
        normalized_url=source_page,
        platform="google_calendar",
        method="google_calendar_ics",
        events=events,
        metadata={
            "calendar_id": calendar_id,
            "ics_url": ics_url,
            "event_count": len(events),
            "window_days_past": WINDOW_DAYS_PAST,
            "window_days_future": WINDOW_DAYS_FUTURE,
        },
    )


# =========================================================
# The Events Calendar / JSON-LD / auto-detect
# =========================================================

def detect_the_events_calendar(url: str, html: str) -> bool:
    return (
        "/wp-content/plugins/the-events-calendar/" in html
        or "/wp-json/tribe/events/v1/events" in html
        or "tribe-events" in html.lower()
        or "the-events-calendar" in html.lower()
        or "polecattavern.com" in url
    )


def detect_wix_events(html: str) -> bool:
    html_lower = html.lower()
    return (
        "wix.com website builder" in html_lower
        or "parastorage.com/services/events-viewer" in html_lower
        or "wix-events" in html_lower
    )


def extract_the_events_calendar_events(source_page: str) -> dict[str, Any]:
    parsed = urlparse(source_page)
    api_url = f"{parsed.scheme}://{parsed.netloc}/wp-json/tribe/events/v1/events"
    start, end = window_start_end()

    params = {
        "per_page": 100,
        "page": 1,
        "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "publish",
    }

    total_pages = 1
    events: list[dict[str, Any]] = []

    while params["page"] <= total_pages:
        payload = request_json(api_url, params=params)
        items = payload.get("events", [])
        total_pages = payload.get("total_pages", 1)

        for item in items:
            venue_info = item.get("venue") or {}
            events.append({
                "source_url": api_url,
                "source_page": source_page,
                "platform": "the_events_calendar",
                "method": "the_events_calendar_rest_api",
                "raw_source_id": item.get("id"),
                "title": item.get("title"),
                "start": item.get("start_date"),
                "end": item.get("end_date"),
                "description": item.get("description"),
                "location": venue_info.get("venue") or venue_info.get("address"),
                "venue": venue_info.get("venue"),
                "address": venue_info.get("address"),
                "city": venue_info.get("city"),
                "state": venue_info.get("stateprovince") or venue_info.get("state"),
                "event_url": item.get("url"),
                "status": item.get("status"),
                "all_day": item.get("all_day"),
                "categories": [cat.get("name") for cat in item.get("categories", []) if cat.get("name")],
                "tags": [tag.get("name") for tag in item.get("tags", []) if tag.get("name")],
            })

        params["page"] += 1

    return _result(
        success=True,
        input_url=source_page,
        normalized_url=source_page,
        platform="the_events_calendar",
        method="the_events_calendar_rest_api",
        events=events,
        metadata={
            "api_url": api_url,
            "event_count": len(events),
            "window_days_past": WINDOW_DAYS_PAST,
            "window_days_future": WINDOW_DAYS_FUTURE,
        },
    )


def extract_json_ld_events(source_page: str, html: str) -> Optional[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script", {"type": "application/ld+json"})
    items: list[dict[str, Any]] = []

    for script in scripts:
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue

        candidates = payload if isinstance(payload, list) else [payload]
        for obj in candidates:
            if isinstance(obj, dict) and obj.get("@type") == "Event":
                items.append(obj)

    if not items:
        return None

    events: list[dict[str, Any]] = []
    for item in items:
        location = item.get("location")
        venue = None
        loc_text = None

        if isinstance(location, dict):
            venue = location.get("name")
            addr = location.get("address")
            if isinstance(addr, dict):
                loc_text = " ".join(filter(None, [
                    addr.get("streetAddress"),
                    addr.get("addressLocality"),
                    addr.get("addressRegion"),
                ]))
            elif isinstance(addr, str):
                loc_text = addr

        events.append({
            "source_url": source_page,
            "source_page": source_page,
            "platform": "json_ld",
            "method": "json_ld_event",
            "raw_source_id": None,
            "title": item.get("name"),
            "start": item.get("startDate"),
            "end": item.get("endDate"),
            "description": item.get("description"),
            "location": loc_text,
            "venue": venue,
            "city": None,
            "state": None,
            "event_url": item.get("url") or source_page,
            "status": None,
            "all_day": None,
            "categories": [],
            "tags": [],
        })

    return _result(
        success=True,
        input_url=source_page,
        normalized_url=source_page,
        platform="json_ld",
        method="json_ld_event",
        events=events,
        metadata={"event_count": len(events)},
    )


# =========================================================
# Wix / Reno Public Market
# =========================================================

def extract_visible_month_year(text: str) -> Optional[tuple[int, int]]:
    for month_name, month_num in MONTH_NAME_TO_NUM.items():
        match = re.search(rf"\b{month_name}\s+(\d{{4}})\b", text, re.IGNORECASE)
        if match:
            return month_num, int(match.group(1))
    return None

def _extract_wix_event_json_objects(html: str) -> list[dict[str, Any]]:
    """
    Extract Wix event-like JSON objects embedded in page HTML.

    This is intentionally broad because Wix embeds event data inside large
    script/model blobs, not always as clean application/json script tags.
    """
    decoder = json.JSONDecoder()
    events: list[dict[str, Any]] = []

    # Good anchor: Wix event objects usually contain all of these nearby.
    for match in re.finditer(r'"scheduling"\s*:\s*\{"config"\s*:\s*\{', html):
        # Walk backward to the start of the containing object.
        start = html.rfind("{", 0, match.start())
        if start == -1:
            continue

        # The immediate { may be scheduling itself, so walk back farther until
        # we find an object that contains title + scheduling.
        candidate_starts = []
        pos = start
        for _ in range(20):
            pos = html.rfind("{", 0, pos)
            if pos == -1:
                break
            candidate_starts.append(pos)

        for obj_start in [start] + candidate_starts:
            try:
                obj, _ = decoder.raw_decode(html[obj_start:])
            except Exception:
                continue

            if not isinstance(obj, dict):
                continue

            scheduling = obj.get("scheduling", {})
            config = scheduling.get("config", {}) if isinstance(scheduling, dict) else {}

            if obj.get("title") and config.get("startDate"):
                events.append(obj)
                break

    # Dedupe by id/start/title
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in events:
        scheduling = event.get("scheduling", {})
        config = scheduling.get("config", {}) if isinstance(scheduling, dict) else {}
        key = (
            str(event.get("id") or ""),
            str(config.get("startDate") or ""),
            str(event.get("title") or ""),
        )
        deduped[key] = event

    return list(deduped.values())

def extract_wix_events_with_playwright(source_page: str) -> dict[str, Any]:
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError(
            "Playwright is not installed. Install it with `pip install playwright` "
            "and run `playwright install chromium`."
        )

    window_start, window_end = window_start_end()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1200})
        page.goto(source_page, wait_until="load", timeout=60000)
        page.wait_for_timeout(5000)

        html = page.content()
        body_text = page.locator("body").inner_text(timeout=10000)

        browser.close()

    raw_events = _extract_wix_event_json_objects(html)

    events: list[dict[str, Any]] = []

    for item in raw_events:
        scheduling = item.get("scheduling", {})
        config = scheduling.get("config", {}) if isinstance(scheduling, dict) else {}

        start_raw = config.get("startDate")
        end_raw = config.get("endDate")

        if not start_raw:
            continue

        try:
            start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00")) if end_raw else None
        except Exception:
            continue

        # Convert UTC/offset datetime to local timezone for consistent downstream handling.
        start_dt = start_dt.astimezone(LOCAL_TZ)
        if end_dt:
            end_dt = end_dt.astimezone(LOCAL_TZ)

        if not (window_start <= start_dt <= window_end):
            continue

        location_data = item.get("location") or {}
        if not isinstance(location_data, dict):
            location_data = {}

        full_address = location_data.get("fullAddress") or {}
        if not isinstance(full_address, dict):
            full_address = {}

        city = full_address.get("city") or "Reno"
        state = full_address.get("subdivision") or "NV"

        venue = location_data.get("name") or "Reno Public Market"
        address = location_data.get("address") or full_address.get("formattedAddress")

        title = normalize_text(item.get("title"))
        description = normalize_text(item.get("description") or item.get("about") or "")

        if not title:
            continue

        events.append({
            "source_url": source_page,
            "source_page": source_page,
            "platform": "wix_events",
            "method": "wix_embedded_event_json",
            "raw_source_id": item.get("id"),
            "title": title,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat() if end_dt else None,
            "description": description,
            "location": venue,
            "venue": venue,
            "city": city,
            "state": state,
            "event_url": source_page,
            "status": item.get("status"),
            "all_day": False,
            "categories": [],
            "tags": [],
        })

    if not events:
        raise ValueError("The page loaded, but no Wix embedded event data was found.")

    events = dedupe_events(events)

    return _result(
        success=True,
        input_url=source_page,
        normalized_url=source_page,
        platform="wix_events",
        method="wix_embedded_event_json",
        events=events,
        metadata={
            "event_count": len(events),
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "warning": "Used embedded Wix event JSON instead of rendered calendar text to avoid incorrect inferred dates.",
            "rendered_text_excerpt": trim_text(body_text, 1000),
        },
    )

# =========================================================
# Custom site parsers
# =========================================================

def _is_generic_live_music_title(title: str) -> bool:
    return normalize_text(title).strip().lower() == "live music"

def _remove_generic_events_if_specific_exists(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    If a specific titled event exists for the same venue/date/time, drop generic
    'Live Music' placeholders for that slot.
    """
    specific_slots = set()

    for event in events:
        title = normalize_text(event.get("title"))
        if title and not _is_generic_live_music_title(title):
            specific_slots.add((
                normalize_text(event.get("venue")).lower(),
                normalize_text(event.get("start")),
            ))

    filtered = []
    for event in events:
        slot = (
            normalize_text(event.get("venue")).lower(),
            normalize_text(event.get("start")),
        )
        title = normalize_text(event.get("title"))

        if _is_generic_live_music_title(title) and slot in specific_slots:
            continue

        filtered.append(event)

    return filtered

def _looks_like_announcement_text(title: str) -> bool:
    lower = normalize_text(title).lower()
    bad_patterns = [
        r"\bannouncing\b",
        r"\beven more live music\b",
        r"\bmondayz\b",
        r"\btuezdays\b",
        r"\bfirst fridayz\b",
    ]
    return any(re.search(pattern, lower) for pattern in bad_patterns)

def extract_zephyr_wine_bar_events(source_page: str) -> dict[str, Any]:
    html = fetch_page_html_with_playwright(source_page)
    soup = BeautifulSoup(html, "html.parser")

    # Use full visible text instead of brittle HTML slicing.
    page_text = soup.get_text("\n", strip=True)
    relevant_text = page_text
    relevant_text_clean = normalize_text(relevant_text)

    now_dt = now_local()
    window_start, window_end = window_start_end()

    visible_month = None
    visible_year = now_dt.year

    month_match = re.search(
        r"\b(" + "|".join(MONTH_NAME_TO_NUM.keys()) + r")\s+line[\s\-]*up\b",
        relevant_text_clean,
        re.IGNORECASE,
    )
    if month_match:
        visible_month = MONTH_NAME_TO_NUM[month_match.group(1).lower()]

    year_match = re.search(r"\b(20\d{2})\b", relevant_text_clean)
    if year_match:
        visible_year = int(year_match.group(1))

    if visible_month is None:
        any_month_match = re.search(
            r"\b(" + "|".join(MONTH_NAME_TO_NUM.keys()) + r")\b",
            relevant_text_clean,
            re.IGNORECASE,
        )
        if any_month_match:
            visible_month = MONTH_NAME_TO_NUM[any_month_match.group(1).lower()]

    if visible_month is None:
        visible_month = now_dt.month

    events: list[dict[str, Any]] = []

    def make_event(
        title: str,
        start_dt: datetime,
        end_dt: datetime | None,
        description: str | None,
        categories: list[str] | None = None,
        recurrence: str | None = None,
    ) -> dict[str, Any]:
        return {
            "source_url": source_page,
            "source_page": source_page,
            "platform": "html_text_page",
            "method": "zephyr_wine_bar_text_parse",
            "raw_source_id": None,
            "title": title,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat() if end_dt else None,
            "description": description,
            "location": "Zephyr Wine Bar",
            "venue": "Zephyr Wine Bar",
            "city": "Reno",
            "state": "NV",
            "event_url": source_page,
            "status": None,
            "all_day": False,
            "categories": categories or ["Music"],
            "tags": [recurrence] if recurrence else [],
        }

    # ---------------------------------------------------------
    # Specific dated lineup entries
    # Example:
    #   April 5th, Sunday – The Road Apples
    # ---------------------------------------------------------
    dated_pattern = re.compile(
        r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2})(?:st|nd|rd|th)?,\s*"
        r"(Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday)\s*[–-]\s*(.+)$",
        re.IGNORECASE,
    )

    lines = [normalize_text(x) for x in relevant_text.splitlines() if normalize_text(x)]

    for line in lines:
        match = dated_pattern.match(line)
        if not match:
            continue

        month_name, day_text, weekday_name, artist_raw = match.groups()
        artist, parsed_start_time, parsed_end_time = _parse_zephyr_artist_and_time(artist_raw)
        artist = normalize_text(artist)

        if not artist:
            continue

        # Skip obvious non-event promo or bad titles.
        if _is_zephyr_intro_line(line):
            continue
        if _looks_like_announcement_text(artist):
            continue
        if _is_zephyr_bad_title(artist):
            continue

        month_num = MONTH_NAME_TO_NUM[month_name.lower()]
        day_num = int(day_text)
        weekday_lower = weekday_name.lower()

        if parsed_start_time and parsed_end_time:
            start_hour, start_minute = parsed_start_time
            end_hour, end_minute = parsed_end_time
        elif weekday_lower == "sunday":
            start_hour, start_minute = 15, 0
            end_hour, end_minute = 18, 0
        elif weekday_lower in {"monday", "tuesday"}:
            start_hour, start_minute = 17, 30
            end_hour, end_minute = 19, 30
        else:
            continue

        event_year = visible_year
        if month_num < now_dt.month - 6:
            event_year += 1

        try:
            start_dt = datetime(
                event_year, month_num, day_num, start_hour, start_minute, tzinfo=LOCAL_TZ
            )
            end_dt = (
                datetime(event_year, month_num, day_num, end_hour, end_minute, tzinfo=LOCAL_TZ)
            )
        except ValueError:
            continue

        if window_start <= start_dt <= window_end:
            events.append(
                make_event(
                    title=artist,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    description=f"{weekday_name} live music at Zephyr Wine Bar.",
                    categories=["Music", "Live Music"],
                )
            )

    # ---------------------------------------------------------
    # Recurring placeholders from announcement/header text
    # Current text pattern:
    #   LIVE MUSIC EVERY SUNDAY, 3PM – 6PM, EVERY MONDAY & TUESDAY, 5:30PM – 7:30PM
    #   ... First Friday ... 5:00 – 7:00pm
    # ---------------------------------------------------------

    sunday_match = re.search(
        r"every sunday,\s*(\d{1,2}(?::\d{2})?\s*[ap]m)\s*[–-]\s*(\d{1,2}(?::\d{2})?\s*[ap]m)",
        relevant_text_clean,
        re.IGNORECASE,
    )
    if sunday_match:
        sunday_start = parse_time_to_24h(sunday_match.group(1))
        sunday_end = parse_time_to_24h(sunday_match.group(2))

        if sunday_start and sunday_end:
            current = window_start.date()
            while current <= window_end.date():
                if current.weekday() == 6:  # Sunday
                    start_dt = (
                        datetime(current.year, current.month, current.day, sunday_start[0], sunday_start[1], tzinfo=LOCAL_TZ)
                    )
                    end_dt = (
                        datetime(current.year, current.month, current.day, sunday_end[0], sunday_end[1], tzinfo=LOCAL_TZ)
                    )
                    events.append(
                        make_event(
                            title="Live Music",
                            start_dt=start_dt,
                            end_dt=end_dt,
                            description="Recurring Sunday live music at Zephyr Wine Bar.",
                            categories=["Music", "Live Music"],
                            recurrence="every_sunday",
                        )
                    )
                current += timedelta(days=1)

    mon_tue_match = re.search(
        r"every monday\s*(?:&|and)\s*tuesday,\s*(\d{1,2}(?::\d{2})?\s*[ap]m)\s*[–-]\s*(\d{1,2}(?::\d{2})?\s*[ap]m)",
        relevant_text_clean,
        re.IGNORECASE,
    )
    if mon_tue_match:
        mon_tue_start = parse_time_to_24h(mon_tue_match.group(1))
        mon_tue_end = parse_time_to_24h(mon_tue_match.group(2))

        if mon_tue_start and mon_tue_end:
            current = window_start.date()
            while current <= window_end.date():
                if current.weekday() in (0, 1):  # Monday, Tuesday
                    start_dt = (
                        datetime(current.year, current.month, current.day, mon_tue_start[0], mon_tue_start[1], tzinfo=LOCAL_TZ)
                    )
                    end_dt = (
                        datetime(current.year, current.month, current.day, mon_tue_end[0], mon_tue_end[1], tzinfo=LOCAL_TZ)
                    )
                    events.append(
                        make_event(
                            title="Live Music",
                            start_dt=start_dt,
                            end_dt=end_dt,
                            description="Recurring Monday/Tuesday live music at Zephyr Wine Bar.",
                            categories=["Music", "Live Music"],
                            recurrence="mondays_tuesdays",
                        )
                    )
                current += timedelta(days=1)

    events = _remove_generic_events_if_specific_exists(events)

    if not events:
        return _result(
            success=False,
            input_url=source_page,
            normalized_url=source_page,
            platform="html_text_page",
            method="zephyr_wine_bar_text_parse",
            events=[],
            metadata={},
            error="No Zephyr Wine Bar music events were found on the page.",
        )

    return _result(
        success=True,
        input_url=source_page,
        normalized_url=source_page,
        platform="html_text_page",
        method="zephyr_wine_bar_text_parse",
        events=events,
        metadata={
            "event_count": len(events),
            "visible_month": visible_month,
            "visible_year": visible_year,
        },
    )

def extract_midtown_music_events(source_page: str) -> dict[str, Any]:
    html = request_text(source_page)
    soup = BeautifulSoup(html, "html.parser")
    now_dt = now_local()
    window_start, window_end = window_start_end()

    lines = [normalize_text(x) for x in soup.get_text("\n", strip=True).splitlines() if normalize_text(x)]

    date_re = re.compile(
        r"^(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,?\s*"
        r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(?P<year>20\d{2}))?$",
        re.IGNORECASE,
    )
    time_re = re.compile(
        r"^(?P<start>\d{1,2}(?::\d{2})?\s*[APap][Mm])\s*[-–]\s*(?P<end>\d{1,2}(?::\d{2})?\s*[APap][Mm])$"
    )

    def looks_like_title(text: str) -> bool:
        if not text:
            return False
        if date_re.match(text) or time_re.match(text):
            return False
        lower = text.lower()
        if any(lower.startswith(p) for p in ("0 events on", "1 event on", "2 events on", "read more")):
            return False
        return True

    events: list[dict[str, Any]] = []
    i = 0

    while i < len(lines):
        title = lines[i]
        if not looks_like_title(title) or i + 1 >= len(lines):
            i += 1
            continue
        
        categories = []
        if not looks_like_music_title(title):
            i += 1
            continue
        
        categories = ["Music", "Live Music"]

        date_match = date_re.match(lines[i + 1])
        if not date_match:
            i += 1
            continue

        desc_lines: list[str] = []
        time_match = None
        j = i + 2
        while j < min(i + 8, len(lines)):
            maybe_time = time_re.match(lines[j])
            if maybe_time:
                time_match = maybe_time
                break
            if not date_re.match(lines[j]):
                desc_lines.append(lines[j])
            j += 1

        if not time_match:
            i += 1
            continue

        month_num = MONTH_NAME_TO_NUM[date_match.group("month").lower()]
        day = int(date_match.group("day"))
        year = int(date_match.group("year") or now_dt.year)

        start_time = parse_time_to_24h(time_match.group("start"))
        end_time = parse_time_to_24h(time_match.group("end"))
        if not start_time or not end_time:
            i = j + 1
            continue

        try:
            start_dt = datetime(year, month_num, day, start_time[0], start_time[1], tzinfo=now_dt.tzinfo)
            end_dt = datetime(year, month_num, day, end_time[0], end_time[1], tzinfo=now_dt.tzinfo)
        except ValueError:
            i = j + 1
            continue

        if window_start <= start_dt <= window_end:
            events.append({
                "source_url": source_page,
                "source_page": source_page,
                "platform": "html_text_page",
                "method": "midtown_music_block_parse",
                "raw_source_id": None,
                "title": title,
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "description": " ".join(desc_lines),
                "location": "Midtown Spirits Wine & Bites",
                "venue": "Midtown Spirits Wine & Bites",
                "city": "Reno",
                "state": "NV",
                "event_url": source_page,
                "status": None,
                "all_day": False,
                "categories": categories,
                "tags": [],
            })

        i = j + 1

    if not events:
        return _result(
            success=False,
            input_url=source_page,
            normalized_url=source_page,
            platform="html_text_page",
            method="midtown_music_block_parse",
            events=[],
            metadata={},
            error="The page loaded, but no Midtown event blocks were parsed.",
        )

    return _result(
        success=True,
        input_url=source_page,
        normalized_url=source_page,
        platform="html_text_page",
        method="midtown_music_block_parse",
        events=events,
        metadata={"event_count": len(events)},
    )


def extract_max_casino_events(source_page: str) -> dict[str, Any]:
    html = request_text(source_page)
    soup = BeautifulSoup(html, "html.parser")
    lines = [normalize_text(x) for x in soup.get_text("\n", strip=True).splitlines() if normalize_text(x)]

    now_dt = now_local()
    tz = now_dt.tzinfo
    window_start, window_end = window_start_end()
    events: list[dict[str, Any]] = []

    def parse_month_day_title(line: str) -> Optional[tuple[int, int, str]]:
        match = re.match(
            r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
            r"(\d{1,2})(?:st|nd|rd|th)?\s*:\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        if not match:
            return None
        return MONTH_NAME_TO_NUM[match.group(1).lower()], int(match.group(2)), normalize_text(match.group(3))

    current_section = None
    for line in lines:
        lower = line.lower()

        if "friday night live music" in lower:
            current_section = "friday_live_music"
            continue

        if "wednesday live entertainment" in lower:
            current_section = "wednesday_live_entertainment"
            continue

        if current_section == "wednesday_live_entertainment":
            continue

        if current_section == "friday_live_music":
            parsed = parse_month_day_title(line)
            if not parsed:
                continue

            month_num, day, title = parsed
            if normalize_text(title).lower() in {"live with ev!", "live with ev"}:
                continue

            year = now_dt.year
            if month_num < now_dt.month - 6:
                year += 1

            try:
                start_dt = datetime(year, month_num, day, 19, 0, tzinfo=tz)
            except ValueError:
                continue

            if not (window_start <= start_dt <= window_end):
                continue

            events.append({
                "source_url": source_page,
                "source_page": source_page,
                "platform": "html_text_page",
                "method": "max_casino_text_parse",
                "raw_source_id": None,
                "title": title,
                "start": start_dt.isoformat(),
                "end": None,
                "description": "Friday Night Live Music at Max Casino.",
                "location": "Max Casino",
                "venue": "Max Casino",
                "city": "Carson City",
                "state": "NV",
                "event_url": source_page,
                "status": None,
                "all_day": False,
                "categories": ["Music", "Live Music"],
                "tags": [],
            })

    return _result(
        success=True,
        input_url=source_page,
        normalized_url=source_page,
        platform="html_text_page",
        method="max_casino_text_parse",
        events=events,
        metadata={
            "event_count": len(events),
            "notes": [
                "Wednesday section intentionally skipped.",
                "Friday 'Live with EV!' entries intentionally excluded.",
            ],
        },
    )

# =========================================================
# Auto router / registry
# =========================================================

def event_calendar_check(url: str) -> dict[str, Any]:
    result = ScrapeResult(
        success=False,
        input_url=url,
        normalized_url=None,
        platform=None,
        method=None,
        events=[],
        metadata={},
        error=None,
    ).as_dict()

    try:
        normalized_url = normalize_url(url)
        html = request_text(normalized_url)

        calendar_id = extract_google_calendar_id_from_html(html)
        if calendar_id:
            return extract_google_calendar_events_via_ics(normalized_url, calendar_id)

        if detect_the_events_calendar(normalized_url, html):
            return extract_the_events_calendar_events(normalized_url)

        json_ld = extract_json_ld_events(normalized_url, html)
        if json_ld:
            return json_ld

        if detect_wix_events(html):
            return extract_wix_events_with_playwright(normalized_url)

        return _result(
            success=False,
            input_url=url,
            normalized_url=normalized_url,
            platform=None,
            method=None,
            events=[],
            metadata={},
            error="The page loaded, but no machine-readable event list was found.",
        )
    except Exception as exc:
        result["error"] = str(exc)
        return result


EXTRACTOR_REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "auto_calendar_check": event_calendar_check,
    "zephyr": extract_zephyr_wine_bar_events,
    "midtown": extract_midtown_music_events,
    "max_casino": extract_max_casino_events,
}