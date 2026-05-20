from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.template.response import TemplateResponse
from django.utils import timezone

from .formatters import format_events
from .image_export import render_event_image
from .models import ScrapeSource
from .scraper_import import run_scrape_import
from .services import (
    filter_events_for_monday_post,
    filter_events_for_thursday_post,
    get_week_events,
)


def group_events_for_preview(events):
    grouped = OrderedDict()
    for event in events:
        day_key = event["start"].date()
        if day_key not in grouped:
            grouped[day_key] = {
                "header": event["start"].strftime("%A, %B %d").replace(" 0", " "),
                "events": [],
            }
        grouped[day_key]["events"].append(event)
    return grouped.values()


def _get_events_for_export_type(reference_date, export_type):
    week_events = get_week_events(reference_date)

    if export_type == "monday":
        return filter_events_for_monday_post(week_events), "Monday Post Export"
    if export_type == "thursday":
        return filter_events_for_thursday_post(week_events), "Thursday Post Export"
    return week_events, "Full Week Export"


def _build_week_label(events, export_type: str) -> str:
    if not events:
        return "No Events"

    start_date = min(e["start"].date() for e in events)
    end_date = max(e["start"].date() for e in events)

    prefix = {
        "monday": "Week Day",
        "thursday": "Weekend",
        "week": "Weekly",
    }.get(export_type, "Weekly")

    if start_date.month == end_date.month:
        return f"{prefix} {start_date.strftime('%B')} {start_date.day} - {end_date.day}"
    return f"{prefix} {start_date.strftime('%B')} {start_date.day} - {end_date.strftime('%B')} {end_date.day}"


def export_view(request):
    export_type = request.GET.get("type", "week")
    date_str = request.GET.get("date")

    if date_str:
        reference_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        reference_date = timezone.localdate()

    day_font_size = int(request.GET.get("day_font_size", 58))
    event_font_size = int(request.GET.get("event_font_size", 32))
    action = request.GET.get("action", "")

    events, title = _get_events_for_export_type(reference_date, export_type)
    formatted_text = format_events(events)
    preview_days = group_events_for_preview(events)
    week_label = _build_week_label(events, export_type)

    image_url = None
    image_path = None
    shrink_report = None

    if action in {"preview_image", "save_image"} and events:
        output_dir = Path(settings.MEDIA_ROOT) / "generated"
        output_dir.mkdir(parents=True, exist_ok=True)

        file_name = f"events_{export_type}_{reference_date.isoformat()}_{uuid4().hex[:8]}.png"
        output_path = output_dir / file_name

        render_result = render_event_image(
            events=events,
            output_path=str(output_path),
            background_path=str(settings.BASE_DIR / "assets" / "wood_background.jpg"),
            logo_path=str(settings.BASE_DIR / "assets" / "swingin_country_logo.png"),
            week_label=week_label,
            day_font_size=day_font_size,
            event_font_size=event_font_size,
        )

        image_url = f"{settings.MEDIA_URL}generated/{file_name}"
        image_path = render_result["output_path"]

        shrink_report = {
            "auto_shrink_applied": render_result["auto_shrink_applied"],
            "requested_day_font_size": render_result["requested_day_font_size"],
            "requested_event_font_size": render_result["requested_event_font_size"],
            "requested_time_font_size": render_result["requested_time_font_size"],
            "final_day_font_size": render_result["final_day_font_size"],
            "final_event_font_size": render_result["final_event_font_size"],
            "final_time_font_size": render_result["final_time_font_size"],
        }

    context = {
        "title": title,
        "formatted_text": formatted_text,
        "preview_days": preview_days,
        "export_type": export_type,
        "selected_date": reference_date.isoformat(),
        "default_font_family": "Georgia",
        "default_header_size": 23,
        "default_event_size": 16,
        "image_url": image_url,
        "image_path": image_path,
        "day_font_size": day_font_size,
        "event_font_size": event_font_size,
        "week_label": week_label,
        "shrink_report": shrink_report,
    }

    return TemplateResponse(
        request,
        "admin/events/export.html",
        context,
    )


def scrape_view(request):
    sources = ScrapeSource.objects.filter(is_enabled=True).order_by("sort_order", "name")
    selected_ids = request.GET.getlist("source_ids")
    action = request.GET.get("action", "")

    selected_ids_int = []
    for value in selected_ids:
        try:
            selected_ids_int.append(int(value))
        except ValueError:
            continue

    scrape_result = None

    if action == "preview":
        scrape_result = run_scrape_import(
            source_ids=selected_ids_int or None,
            preview_only=True,
        )
    elif action == "import":
        scrape_result = run_scrape_import(
            source_ids=selected_ids_int or None,
            preview_only=False,
        )

    context = {
        "title": "Scrape Sources",
        "sources": sources,
        "selected_ids": selected_ids_int,
        "scrape_result": scrape_result,
        "action": action,
    }

    return TemplateResponse(
        request,
        "admin/events/scrape.html",
        context,
    )