from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import ScrapeRun, ScrapeSource, ScrapedEvent
from .event_scraper import (
    EXTRACTOR_REGISTRY,
)


@dataclass
class ImportStats:
    source_name: str
    scraped_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    duplicate_match_count: int = 0
    errors: list[str] | None = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def _normalize_string(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def _safe_parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None

    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt.astimezone(timezone.get_current_timezone())


def _event_fingerprint(source_name: str, event: dict[str, Any]) -> str:
    external_id = _normalize_string(event.get("raw_source_id") or event.get("external_event_id"))
    start_dt = _normalize_string(event.get("start"))
    venue = _normalize_string(event.get("venue"))
    location = _normalize_string(event.get("location"))
    event_url = _normalize_string(event.get("event_url"))
    title = _normalize_string(event.get("title"))

    if external_id:
        base = f"{source_name}|external|{external_id}"
    else:
        base = f"{source_name}|{start_dt}|{venue}|{location}|{event_url}|{title}"

    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _run_source_extractor(source: ScrapeSource) -> dict:
    extractor = EXTRACTOR_REGISTRY[source.extractor_key]
    return extractor(source.url)


def _derive_relevance(event: dict[str, Any]) -> tuple[str, str]:
    likely_relevant = bool(event.get("likely_relevant"))
    if likely_relevant:
        return "relevant", "Marked likely_relevant by scraper."
    return "uncertain", "Not marked likely_relevant by scraper."


def _upsert_scraped_event(
    *,
    scrape_run: ScrapeRun,
    source: ScrapeSource,
    event: dict[str, Any],
) -> tuple[ScrapedEvent, bool]:
    start_dt = _safe_parse_datetime(event.get("start"))
    end_dt = _safe_parse_datetime(event.get("end"))

    if not start_dt:
        raise ValueError(f"Event missing valid start datetime: {event!r}")

    external_event_id = str(event.get("raw_source_id") or event.get("external_event_id") or "").strip()
    fingerprint = _event_fingerprint(source.name, event)

    relevance_status, relevance_reason = _derive_relevance(event)

    existing = None

    if external_event_id:
        existing = (
            ScrapedEvent.objects
            .filter(source_name=source.name, external_event_id=external_event_id)
            .first()
        )

    if existing is None:
        existing = (
            ScrapedEvent.objects
            .filter(
                source_name=source.name,
                start_datetime=start_dt,
                venue=event.get("venue") or "",
                location=event.get("location") or "",
                event_url=event.get("event_url") or "",
            )
            .first()
        )

    payload = {
        "scrape_run": scrape_run,
        "source_name": source.name,
        "source_page": event.get("source_page") or source.url,
        "event_url": event.get("event_url") or "",
        "external_event_id": external_event_id,
        "title": event.get("title") or "",
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "venue": event.get("venue") or "",
        "city": event.get("city") or "",
        "state": event.get("state") or "",
        "location": event.get("location") or "",
        "categories": event.get("categories") or [],
        "summary": event.get("summary") or "",
        "relevance_status": relevance_status,
        "relevance_reason": relevance_reason,
        "raw_payload": {
            "normalized_event": event,
            "import_fingerprint": fingerprint,
        },
        "last_seen_at": timezone.now(),
    }

    if existing:
        for field, value in payload.items():
            setattr(existing, field, value)
        existing.save()
        return existing, False

    obj = ScrapedEvent.objects.create(
        first_seen_at=timezone.now(),
        review_status="unreviewed",
        review_notes="",
        **payload,
    )
    return obj, True


@transaction.atomic
def run_scrape_import(
    *,
    source_ids: list[int] | None = None,
    preview_only: bool = True,
) -> dict[str, Any]:
    if source_ids:
        sources = list(
            ScrapeSource.objects.filter(is_enabled=True, id__in=source_ids).order_by("sort_order", "name")
        )
    else:
        sources = list(
            ScrapeSource.objects.filter(is_enabled=True).order_by("sort_order", "name")
        )

    run_started = timezone.now()
    scrape_run = None

    if not preview_only:
        scrape_run = ScrapeRun.objects.create(
            source_name="multiple_sources" if len(sources) != 1 else sources[0].name,
            status="started",
            started_at=run_started,
            notes="Preview disabled; importing into ScrapedEvent.",
        )

    results: list[dict[str, Any]] = []
    per_source_stats: list[ImportStats] = []

    try:
        for source in sources:
            stats = ImportStats(source_name=source.name)

            try:
                result = _run_source_extractor(source)
                events = result.get("events", [])

                stats.scraped_count = len(events)

                result_row = {
                    "source_id": source.id,
                    "source_name": source.name,
                    "extractor_key": source.extractor_key,
                    "success": result.get("success", False),
                    "error": result.get("error"),
                    "event_count": len(events),
                    "events": events if preview_only else [],
                    "metadata": result.get("metadata", {}),
                }

                results.append(result_row)

                if not result.get("success"):
                    stats.errors.append(result.get("error") or "Unknown scrape error")
                    per_source_stats.append(stats)
                    continue

                if preview_only:
                    per_source_stats.append(stats)
                    continue

                for event in events:
                    _, created = _upsert_scraped_event(
                        scrape_run=scrape_run,
                        source=source,
                        event=event,
                    )
                    if created:
                        stats.created_count += 1
                    else:
                        stats.updated_count += 1

                per_source_stats.append(stats)

            except Exception as exc:
                stats.errors.append(str(exc))
                results.append({
                    "source_id": source.id,
                    "source_name": source.name,
                    "extractor_key": source.extractor_key,
                    "success": False,
                    "error": str(exc),
                    "event_count": 0,
                    "events": [],
                    "metadata": {},
                })
                per_source_stats.append(stats)

        if not preview_only and scrape_run:
            total_events = sum(s.scraped_count for s in per_source_stats)
            relevant_count = ScrapedEvent.objects.filter(
                scrape_run=scrape_run,
                relevance_status="relevant",
            ).count()

            scrape_run.status = "completed"
            scrape_run.completed_at = timezone.now()
            scrape_run.events_found = total_events
            scrape_run.relevant_count = relevant_count
            scrape_run.irrelevant_count = 0
            scrape_run.error_count = sum(len(s.errors) for s in per_source_stats)
            scrape_run.save()

        return {
            "preview_only": preview_only,
            "scrape_run_id": scrape_run.id if scrape_run else None,
            "results": results,
            "per_source_stats": [
                {
                    "source_name": s.source_name,
                    "scraped_count": s.scraped_count,
                    "created_count": s.created_count,
                    "updated_count": s.updated_count,
                    "skipped_count": s.skipped_count,
                    "duplicate_match_count": s.duplicate_match_count,
                    "errors": s.errors,
                }
                for s in per_source_stats
            ],
        }

    except Exception:
        if not preview_only and scrape_run:
            scrape_run.status = "failed"
            scrape_run.completed_at = timezone.now()
            scrape_run.save()
        raise