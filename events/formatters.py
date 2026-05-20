from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any
import textwrap


def format_time(dt: datetime) -> str:
    """
    Format time as '8:00 PM' with no leading zero.
    """
    return dt.strftime("%I:%M %p").lstrip("0")


def format_day_header(dt: datetime) -> str:
    """
    Format day header like 'Monday, April 14'
    """
    return dt.strftime("%A, %B %d").replace(" 0", " ")


def group_events_by_day(events: list[dict[str, Any]]) -> dict:
    grouped = defaultdict(list)

    for event in events:
        grouped[event["start"].date()].append(event)

    return dict(sorted(grouped.items()))


def wrap_event_text(text: str, width: int) -> list[str]:
    """
    Wrap text into multiple lines with consistent width.
    """
    return textwrap.wrap(text, width=width)


def format_events(events: list[dict]) -> str:
    """
    Format events with indentation for wrapped lines.
    """
    if not events:
        return "No events found for the selected range."

    grouped = group_events_by_day(events)
    output_lines = []

    TIME_WIDTH = 8  # enough for "10:00 PM"
    TEXT_WRAP_WIDTH = 60  # adjust if needed

    for _, day_events in grouped.items():
        header = format_day_header(day_events[0]["start"])
        output_lines.append(header)

        for event in day_events:
            time_str = format_time(event["start"])
            time_block = f"{time_str:<{TIME_WIDTH}}"

            raw_location = event.get("location") or event.get("venue") or ""
            city = event.get("city")

            location = normalize_location(raw_location, city)
            text = event["title"]
            if location:
                text += f" - {location}"

            wrapped_lines = wrap_event_text(text, TEXT_WRAP_WIDTH)

            # First line
            output_lines.append(f"{time_block}— {wrapped_lines[0]}")

            # Wrapped lines (indented)
            indent = " " * (TIME_WIDTH + 2)  # align under text
            for line in wrapped_lines[1:]:
                output_lines.append(f"{indent}{line}")

        output_lines.append("")

    return "\n".join(output_lines).strip()

import re


def normalize_location(location: str | None, city: str | None) -> str:
    """
    If the city already appears in the location text, return location as-is.
    Otherwise append the city in parentheses.
    Uses loose matching to handle punctuation and spacing differences.
    """
    if not location:
        return ""

    if not city:
        return location.strip()

    location_clean = location.strip()
    city_clean = city.strip()

    if not city_clean:
        return location_clean

    normalized_location = re.sub(r"[^a-z0-9]+", " ", location_clean.lower()).strip()
    normalized_city = re.sub(r"[^a-z0-9]+", " ", city_clean.lower()).strip()

    if normalized_city and normalized_city in normalized_location:
        return location_clean

    return f"{location_clean} ({city_clean})"