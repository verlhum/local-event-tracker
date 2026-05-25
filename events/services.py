from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from django.utils import timezone

from .models import (
    ManualSingleEvent,
    ManualRecurringEvent,
    RecurringException,
    ScrapedEvent,
)


LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def _safe_categories(categories: Any) -> list[str]:
    """
    Normalize categories into a list of strings.
    """
    if categories is None:
        return []
    if isinstance(categories, list):
        return [str(x) for x in categories if x not in (None, "")]
    if isinstance(categories, str) and categories.strip():
        return [categories.strip()]
    return []


def _combine_local_datetime(event_date: date, event_time: time | None) -> datetime | None:
    """
    Combine a local date and time into a timezone-aware datetime in America/Los_Angeles.
    """
    if event_time is None:
        return None
    return datetime.combine(event_date, event_time, tzinfo=LOCAL_TZ)


def _valid_month_day(year: int, month: int, day: int) -> bool:
    """
    Return True if the given day exists for the year/month.
    """
    try:
        date(year, month, day)
        return True
    except ValueError:
        return False


def _get_monthly_matching_dates(year: int, month: int, weekday: int) -> list[date]:
    """
    Return all dates in a given month matching the provided weekday.
    weekday: 0=Monday ... 6=Sunday
    """
    matches: list[date] = []
    for day_num in range(1, 32):
        if _valid_month_day(year, month, day_num):
            d = date(year, month, day_num)
            if d.weekday() == weekday:
                matches.append(d)
    return matches


def get_week_bounds(reference_date: date | None = None) -> tuple[date, date]:
    """
    Return the Monday and Sunday for the calendar week containing reference_date.
    """
    reference_date = reference_date or timezone.localdate()
    monday = reference_date - timedelta(days=reference_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _is_recurring_event_active_for_date(
    recurring_event: ManualRecurringEvent,
    current_date: date,
) -> bool:
    """
    Determine whether a recurring rule should generate an occurrence on current_date.
    Supports:
      - weekly
      - monthly_weekday
      - weekly_interval
    """
    if recurring_event.status != "active":
        return False

    if current_date < recurring_event.start_date:
        return False

    if recurring_event.end_date and current_date > recurring_event.end_date:
        return False

    if recurring_event.recurrence_type == "weekly":
        return (
            recurring_event.weekday is not None
            and current_date.weekday() == recurring_event.weekday
        )

    if recurring_event.recurrence_type == "weekly_interval":
        if recurring_event.weekday is None:
            return False

        if recurring_event.anchor_date is None:
            return False

        if not recurring_event.interval_weeks or recurring_event.interval_weeks < 1:
            return False

        if current_date.weekday() != recurring_event.weekday:
            return False

        days_since_anchor = (current_date - recurring_event.anchor_date).days

        if days_since_anchor < 0:
            return False

        if days_since_anchor % 7 != 0:
            return False

        weeks_since_anchor = days_since_anchor // 7

        return weeks_since_anchor % recurring_event.interval_weeks == 0

    if recurring_event.recurrence_type == "monthly_weekday":
        if recurring_event.weekday is None or recurring_event.week_of_month is None:
            return False

        if current_date.weekday() != recurring_event.weekday:
            return False

        matching_dates = _get_monthly_matching_dates(
            current_date.year,
            current_date.month,
            recurring_event.weekday,
        )

        if not matching_dates:
            return False

        if recurring_event.week_of_month == -1:
            return current_date == matching_dates[-1]

        if recurring_event.week_of_month < 1:
            return False

        index = recurring_event.week_of_month - 1
        if index >= len(matching_dates):
            return False

        return current_date == matching_dates[index]

    return False


def _apply_recurring_exception(
    recurring_event: ManualRecurringEvent,
    occurrence_date: date,
) -> dict[str, Any] | None:
    """
    Apply any exception for a recurring event occurrence.
    Returns:
      - None if the event occurrence should be canceled
      - a dict of final field values otherwise
    """
    exception = RecurringException.objects.filter(
        recurring_event=recurring_event,
        occurrence_date=occurrence_date,
    ).first()

    if exception and exception.exception_type == "cancel_occurrence":
        return None

    title = recurring_event.title
    start_time = recurring_event.start_time
    end_time = recurring_event.end_time
    venue = recurring_event.venue
    city = recurring_event.city
    state = recurring_event.state
    location = recurring_event.location
    categories = _safe_categories(recurring_event.categories)
    summary = recurring_event.summary_template
    notes = recurring_event.notes
    event_url = recurring_event.event_url
    source_page = recurring_event.source_page

    if exception and exception.exception_type == "override_occurrence":
        title = exception.override_title or title
        start_time = exception.override_start_time or start_time
        end_time = exception.override_end_time or end_time
        venue = exception.override_venue or venue
        city = exception.override_city or city
        state = exception.override_state or state
        location = exception.override_location or location

        override_categories = _safe_categories(exception.override_categories)
        if override_categories:
            categories = override_categories

        summary = exception.override_summary or summary
        notes = exception.override_notes or notes

    start_dt = _combine_local_datetime(occurrence_date, start_time)
    end_dt = _combine_local_datetime(occurrence_date, end_time)

    return {
        "source_type": "manual_recurring",
        "source_id": recurring_event.id,
        "title": title,
        "start": start_dt,
        "end": end_dt,
        "venue": venue,
        "city": city,
        "state": state,
        "location": location,
        "categories": categories,
        "summary": summary,
        "notes": notes,
        "event_url": event_url,
        "source_page": source_page,
        "status": recurring_event.status,
        "occurrence_date": occurrence_date,
        "exception_applied": exception is not None,
        "exception_id": exception.id if exception else None,
    }


def _serialize_single_event(single_event: ManualSingleEvent) -> dict[str, Any]:
    """
    Convert a ManualSingleEvent model instance into a normalized event dict.
    """
    start_dt = single_event.start_datetime
    end_dt = single_event.end_datetime

    if timezone.is_naive(start_dt):
        start_dt = timezone.make_aware(start_dt, LOCAL_TZ)
    else:
        start_dt = timezone.localtime(start_dt, LOCAL_TZ)

    if end_dt:
        if timezone.is_naive(end_dt):
            end_dt = timezone.make_aware(end_dt, LOCAL_TZ)
        else:
            end_dt = timezone.localtime(end_dt, LOCAL_TZ)

    return {
        "source_type": "manual_single",
        "source_id": single_event.id,
        "title": single_event.title,
        "start": start_dt,
        "end": end_dt,
        "venue": single_event.venue,
        "city": single_event.city,
        "state": single_event.state,
        "location": single_event.location,
        "categories": _safe_categories(single_event.categories),
        "summary": single_event.summary,
        "notes": single_event.notes,
        "event_url": single_event.event_url,
        "source_page": single_event.source_page,
        "status": single_event.status,
        "occurrence_date": start_dt.date(),
        "exception_applied": False,
        "exception_id": None,
    }


def _serialize_scraped_event(scraped_event: ScrapedEvent) -> dict[str, Any]:
    """
    Convert a ScrapedEvent model instance into the same normalized event dict
    used by manual events.
    """
    start_dt = scraped_event.start_datetime
    end_dt = scraped_event.end_datetime

    if timezone.is_naive(start_dt):
        start_dt = timezone.make_aware(start_dt, LOCAL_TZ)
    else:
        start_dt = timezone.localtime(start_dt, LOCAL_TZ)

    if end_dt:
        if timezone.is_naive(end_dt):
            end_dt = timezone.make_aware(end_dt, LOCAL_TZ)
        else:
            end_dt = timezone.localtime(end_dt, LOCAL_TZ)

    return {
        "source_type": "scraped",
        "source_id": scraped_event.id,
        "title": scraped_event.title,
        "start": start_dt,
        "end": end_dt,
        "venue": scraped_event.venue,
        "city": scraped_event.city,
        "state": scraped_event.state,
        "location": scraped_event.location,
        "categories": _safe_categories(scraped_event.categories),
        "summary": scraped_event.summary,
        "notes": scraped_event.review_notes or "",
        "event_url": scraped_event.event_url,
        "source_page": scraped_event.source_page,
        "status": scraped_event.review_status,
        "occurrence_date": start_dt.date(),
        "exception_applied": False,
        "exception_id": None,
        "source_name": scraped_event.source_name,
        "relevance_status": scraped_event.relevance_status,
    }


def _get_scraped_events(start_date: date, end_date: date) -> list[dict[str, Any]]:
    """
    Return scraped events that should be included in the final calendar.

    Included:
      - relevance_status='relevant'
    Excluded review statuses:
      - hidden
      - canceled
      - duplicate
      - bad_scrape
    """
    scraped_events = (
        ScrapedEvent.objects.filter(
            start_datetime__date__gte=start_date,
            start_datetime__date__lte=end_date,
            relevance_status="relevant",
        )
        .exclude(review_status__in=["hidden", "canceled", "duplicate", "bad_scrape"])
        .order_by("start_datetime", "title", "id")
    )

    return [_serialize_scraped_event(obj) for obj in scraped_events]


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Dedupe combined manual + scraped events.

    Preference:
      - manual_single
      - manual_recurring
      - scraped

    This prevents double-posting the same event if it exists manually and in scraped data.
    """
    priority = {
        "manual_single": 0,
        "manual_recurring": 1,
        "scraped": 2,
    }

    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}

    for event in events:
        key = (
            event["start"],
            (event.get("venue") or "").strip().lower(),
            event["title"].strip().lower(),
        )

        existing = grouped.get(key)
        if existing is None:
            grouped[key] = event
            continue

        existing_priority = priority.get(existing.get("source_type"), 99)
        current_priority = priority.get(event.get("source_type"), 99)

        if current_priority < existing_priority:
            grouped[key] = event

    deduped = list(grouped.values())
    deduped.sort(key=lambda e: (e["start"], e["title"], e["source_type"], e["source_id"]))
    return deduped


def get_events(start_date: date, end_date: date) -> list[dict[str, Any]]:
    """
    Return all final-calendar events between start_date and end_date inclusive.

    Includes:
      - active manual single events
      - generated occurrences from active recurring events
      - recurring exceptions applied
      - relevant scraped events not hidden/canceled/duplicate/bad_scrape
    """
    if start_date > end_date:
        raise ValueError("start_date cannot be after end_date")

    events: list[dict[str, Any]] = []

    # Manual single events
    single_events = (
        ManualSingleEvent.objects.filter(
            status="active",
            start_datetime__date__gte=start_date,
            start_datetime__date__lte=end_date,
        )
        .order_by("start_datetime", "id")
    )

    for single_event in single_events:
        events.append(_serialize_single_event(single_event))

    # Manual recurring events
    recurring_events = (
        ManualRecurringEvent.objects.filter(
            status="active",
            start_date__lte=end_date,
        )
        .order_by("title", "id")
    )

    for recurring_event in recurring_events:
        current_date = max(start_date, recurring_event.start_date)
        final_date = end_date

        if recurring_event.end_date:
            final_date = min(final_date, recurring_event.end_date)

        while current_date <= final_date:
            if _is_recurring_event_active_for_date(recurring_event, current_date):
                occurrence = _apply_recurring_exception(recurring_event, current_date)
                if occurrence is not None:
                    events.append(occurrence)

            current_date += timedelta(days=1)

    # Scraped events
    events.extend(_get_scraped_events(start_date, end_date))

    # Combined dedupe + final sort
    return _dedupe_events(events)


def get_week_events(reference_date: date | None = None) -> list[dict[str, Any]]:
    """
    Return all events for the Monday-Sunday week containing reference_date.
    If reference_date is None, use the current local date.
    """
    monday, sunday = get_week_bounds(reference_date)
    return get_events(monday, sunday)


def filter_events_for_monday_post(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Filter a weekly event list down to Monday-Friday.
    """
    return [event for event in events if event["start"].weekday() <= 4]


def filter_events_for_thursday_post(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Filter a weekly event list down to Thursday-Sunday.
    """
    return [event for event in events if event["start"].weekday() >= 3]


def get_current_week_events(reference_date: date):
    return get_week_events(reference_date)


def get_current_monday_post_events(reference_date: date):
    return filter_events_for_monday_post(get_week_events(reference_date))


def get_current_thursday_post_events(reference_date: date):
    return filter_events_for_thursday_post(get_week_events(reference_date))

