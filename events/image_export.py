from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .formatters import normalize_location


# ---------- Configuration ----------

@dataclass
class ImageTheme:
    output_size: tuple[int, int] = (2048, 2048)

    # Margins / layout
    left_margin: int = 150
    right_margin: int = 150
    top_margin: int = 110
    bottom_margin: int = 120
    content_top: int = 520
    logo_max_width: int = 500
    logo_bottom_margin: int = 80
    logo_right_margin: int = 70

    # Text
    text_color: tuple[int, int, int] = (25, 25, 25)
    accent_color: tuple[int, int, int] = (90, 90, 90)

    # Fonts
    title_font_path: str | None = None
    subtitle_font_path: str | None = None
    heading_font_path: str | None = None
    body_font_path: str | None = None
    body_bold_font_path: str | None = None

    title_font_size: int = 110
    subtitle_font_size: int = 60
    range_font_size: int = 60
    day_font_size: int = 64
    event_font_size: int = 40
    time_font_size: int = 40

    # Spacing
    title_subtitle_gap: int = 10
    subtitle_range_gap: int = 60
    day_gap_above: int = 18
    day_gap_below: int = 12
    event_line_gap: int = 8
    day_block_gap: int = 18

    # Wrapping
    time_column_gap: int = 14
    indent_extra: int = 6


# ---------- Font helpers ----------

WINDOWS_FONT_CANDIDATES = {
    "georgia": [
        r"C:\Windows\Fonts\georgia.ttf",
    ],
    "georgia_bold": [
        r"C:\Windows\Fonts\georgiab.ttf",
    ],
    "georgia_italic": [
        r"C:\Windows\Fonts\georgiai.ttf",
    ],
    "georgia_bold_italic": [
        r"C:\Windows\Fonts\georgiaz.ttf",
    ],
    "times": [
        r"C:\Windows\Fonts\times.ttf",
        r"C:\Windows\Fonts\times.ttf",
    ],
    "times_bold": [
        r"C:\Windows\Fonts\timesbd.ttf",
    ],
    "script": [
        r"C:\Windows\Fonts\segoesc.ttf",
        r"C:\Windows\Fonts\seguisb.ttf",
        r"C:\Windows\Fonts\BRADHITC.TTF",
        r"C:\Windows\Fonts\comic.ttf",
    ],
}


def _first_existing(paths: list[str]) -> str | None:
    for path in paths:
        if Path(path).exists():
            return path
    return None


def _load_font(path: str | None, size: int, fallback_group: str = "georgia") -> ImageFont.FreeTypeFont:
    chosen = path or _first_existing(WINDOWS_FONT_CANDIDATES.get(fallback_group, []))
    if chosen:
        return ImageFont.truetype(chosen, size=size)
    return ImageFont.load_default()


def build_default_theme() -> ImageTheme:
    return ImageTheme(
        title_font_path="assets/fonts/Caveat-Bold.ttf",
        subtitle_font_path="assets/fonts/Caveat-Regular.ttf",
        heading_font_path=_first_existing(WINDOWS_FONT_CANDIDATES["georgia_bold"]),
        body_font_path=_first_existing(WINDOWS_FONT_CANDIDATES["georgia"]),
        body_bold_font_path=_first_existing(WINDOWS_FONT_CANDIDATES["georgia_bold"]),
    )


# ---------- Drawing helpers ----------

def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    image_width: int,
) -> int:
    w, h = _measure_text(draw, text, font)
    x = (image_width - w) // 2
    draw.text((x, y), text, font=font, fill=fill)
    return y + h


def _fit_background(background_path: str, output_size: tuple[int, int]) -> Image.Image:
    bg = Image.open(background_path).convert("RGB")
    target_w, target_h = output_size
    src_w, src_h = bg.size

    src_ratio = src_w / src_h
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        # crop width
        new_w = int(src_h * target_ratio)
        left = (src_w - new_w) // 2
        bg = bg.crop((left, 0, left + new_w, src_h))
    else:
        # crop height
        new_h = int(src_w / target_ratio)
        top = (src_h - new_h) // 2
        bg = bg.crop((0, top, src_w, top + new_h))

    return bg.resize(output_size, Image.Resampling.LANCZOS)


def _wrap_text_by_pixels(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]

    for word in words[1:]:
        candidate = f"{current} {word}"
        candidate_w, _ = _measure_text(draw, candidate, font)
        if candidate_w <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word

    lines.append(current)
    return lines


def _draw_event_with_hanging_indent(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    max_width: int,
    time_text: str,
    body_text: str,
    time_font: ImageFont.FreeTypeFont,
    body_font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    gap: int,
    indent_extra: int,
    line_gap: int,
) -> int:
    time_w, time_h = _measure_text(draw, time_text, time_font)
    text_x = x + time_w + gap
    available_width = max_width - (text_x - x)

    wrapped = _wrap_text_by_pixels(draw, body_text, body_font, available_width)
    if not wrapped:
        wrapped = [""]

    # First line
    draw.text((x, y), time_text, font=time_font, fill=fill)
    draw.text((text_x, y), wrapped[0], font=body_font, fill=fill)

    _, body_h = _measure_text(draw, wrapped[0], body_font)
    line_height = max(time_h, body_h)
    y += line_height + line_gap

    # Hanging indent lines
    continuation_x = text_x + indent_extra
    continuation_width = max_width - (continuation_x - x)

    for line in wrapped[1:]:
        rewrapped = _wrap_text_by_pixels(draw, line, body_font, continuation_width)
        for subline in rewrapped:
            draw.text((continuation_x, y), subline, font=body_font, fill=fill)
            _, sub_h = _measure_text(draw, subline, body_font)
            y += sub_h + line_gap

    return y


def _resize_logo(logo: Image.Image, max_width: int) -> Image.Image:
    if logo.width <= max_width:
        return logo
    ratio = max_width / logo.width
    new_size = (int(logo.width * ratio), int(logo.height * ratio))
    return logo.resize(new_size, Image.Resampling.LANCZOS)


def _group_events(events: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        header = event["start"].strftime("%A, %B %d").replace(" 0", " ")
        grouped.setdefault(header, []).append(event)
    return list(grouped.items())


def _event_display_text(event: dict[str, Any]) -> str:
    title = event["title"]
    raw_location = event.get("location") or event.get("venue") or ""
    city = event.get("city")
    location = normalize_location(raw_location, city)

    if location:
        return f"{title} — {location}"
    return title


# ---------- Layout calculation ----------

def _content_height(
    draw: ImageDraw.ImageDraw,
    grouped_events: list[tuple[str, list[dict[str, Any]]]],
    theme: ImageTheme,
) -> int:
    day_font = _load_font(theme.heading_font_path, theme.day_font_size, "georgia_bold")
    body_font = _load_font(theme.body_font_path, theme.event_font_size, "georgia")
    time_font = _load_font(theme.body_bold_font_path, theme.time_font_size, "georgia_bold")

    content_width = theme.output_size[0] - theme.left_margin - theme.right_margin
    total = 0

    for day_header, day_events in grouped_events:
        _, day_h = _measure_text(draw, day_header, day_font)
        total += theme.day_gap_above + day_h + theme.day_gap_below

        for event in day_events:
            time_text = event["start"].strftime("%I:%M %p").lstrip("0")
            body_text = _event_display_text(event)

            time_w, time_h = _measure_text(draw, time_text, time_font)
            available_width = content_width - time_w - theme.time_column_gap
            wrapped = _wrap_text_by_pixels(draw, body_text, body_font, available_width)

            _, body_h = _measure_text(draw, "Ag", body_font)
            line_height = max(time_h, body_h)
            total += line_height

            if len(wrapped) > 1:
                total += (len(wrapped) - 1) * (body_h + theme.event_line_gap)

            total += theme.event_line_gap

        total += theme.day_block_gap

    return total


def _shrink_to_fit(
    draw: ImageDraw.ImageDraw,
    grouped_events: list[tuple[str, list[dict[str, Any]]]],
    theme: ImageTheme,
    max_content_height: int,
) -> ImageTheme:
    working = ImageTheme(**theme.__dict__)

    while True:
        needed = _content_height(draw, grouped_events, working)
        if needed <= max_content_height:
            return working

        # shrink body first, then day, then range/title slightly
        if working.event_font_size > 26:
            working.event_font_size -= 1
            working.time_font_size = max(working.time_font_size - 1, 26)
        elif working.day_font_size > 44:
            working.day_font_size -= 1
        elif working.range_font_size > 42:
            working.range_font_size -= 1
        elif working.title_font_size > 72:
            working.title_font_size -= 1
            working.subtitle_font_size = max(working.subtitle_font_size - 1, 34)
        else:
            return working


# ---------- Public renderer ----------

def render_event_image(
    events: list[dict[str, Any]],
    output_path: str,
    background_path: str,
    logo_path: str | None = None,
    week_label: str | None = None,
    title: str = "Upcoming Dance and Music Events",
    subtitle: str = "Reno · Sparks · Carson City",
    theme: ImageTheme | None = None,
    day_font_size: int | None = None,
    event_font_size: int | None = None,
    time_font_size: int | None = None,
) -> dict[str, Any]:
    """
    Render a square events image.

    events:
        output from services.py
    output_path:
        target PNG path
    background_path:
        separate background image path
    logo_path:
        optional transparent logo image path
    week_label:
        optional date-range label like 'Week Day April 13 - April 17'
    """
    if not events:
        raise ValueError("No events provided.")

    theme = theme or build_default_theme()

    if day_font_size is not None:
        theme.day_font_size = day_font_size

    if event_font_size is not None:
        theme.event_font_size = event_font_size

    if time_font_size is not None:
        theme.time_font_size = time_font_size
    elif event_font_size is not None:
        theme.time_font_size = event_font_size

    requested_day_font_size = theme.day_font_size
    requested_event_font_size = theme.event_font_size
    requested_time_font_size = theme.time_font_size
    grouped_events = _group_events(events)

    base = _fit_background(background_path, theme.output_size)
    canvas = base.convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    # temporary draw for fit calculations
    max_content_height = theme.output_size[1] - theme.content_top - theme.bottom_margin - 300
    theme = _shrink_to_fit(draw, grouped_events, theme, max_content_height)

    title_font = _load_font(theme.title_font_path, theme.title_font_size, "script")
    subtitle_font = _load_font(theme.subtitle_font_path, theme.subtitle_font_size, "script")
    range_font = _load_font(theme.heading_font_path, theme.range_font_size, "georgia_bold")
    day_font = _load_font(theme.heading_font_path, theme.day_font_size, "georgia_bold")
    body_font = _load_font(theme.body_font_path, theme.event_font_size, "georgia")
    time_font = _load_font(theme.body_bold_font_path, theme.time_font_size, "georgia_bold")

    y = theme.top_margin
    y = _draw_centered(draw, y, title, title_font, theme.accent_color, theme.output_size[0])
    y += theme.title_subtitle_gap
    y = _draw_centered(draw, y, subtitle, subtitle_font, theme.accent_color, theme.output_size[0])

    if week_label:
        y += theme.subtitle_range_gap
        y = _draw_centered(draw, y, week_label, range_font, theme.text_color, theme.output_size[0])

    y = max(y + 15, theme.content_top)
    content_width = theme.output_size[0] - theme.left_margin - theme.right_margin

    for day_header, day_events in grouped_events:
        y += theme.day_gap_above
        draw.text((theme.left_margin, y), day_header, font=day_font, fill=theme.text_color)
        _, day_h = _measure_text(draw, day_header, day_font)
        y += day_h + theme.day_gap_below

        for event in day_events:
            start = event["start"]
            end = event.get("end")

            if end:
                time_text = f"{start.strftime('%I:%M %p').lstrip('0')} - {end.strftime('%I:%M %p').lstrip('0')}"
            else:
                time_text = start.strftime("%I:%M %p").lstrip("0")

            body_text = _event_display_text(event)

            y = _draw_event_with_hanging_indent(
                draw=draw,
                x=theme.left_margin,
                y=y,
                max_width=content_width,
                time_text=time_text,
                body_text=body_text,
                time_font=time_font,
                body_font=body_font,
                fill=theme.text_color,
                gap=theme.time_column_gap,
                indent_extra=theme.indent_extra,
                line_gap=theme.event_line_gap,
            )

        y += theme.day_block_gap

    if logo_path:
        logo = Image.open(logo_path).convert("RGBA")
        logo = _resize_logo(logo, theme.logo_max_width)
        logo_x = theme.output_size[0] - logo.width - theme.logo_right_margin
        logo_y = theme.output_size[1] - logo.height - theme.logo_bottom_margin
        canvas.alpha_composite(logo, (logo_x, logo_y))

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_file, format="PNG")

    return {
        "output_path": str(output_file),
        "requested_day_font_size": requested_day_font_size,
        "requested_event_font_size": requested_event_font_size,
        "requested_time_font_size": requested_time_font_size,
        "final_day_font_size": theme.day_font_size,
        "final_event_font_size": theme.event_font_size,
        "final_time_font_size": theme.time_font_size,
        "auto_shrink_applied": (
            theme.day_font_size != requested_day_font_size
            or theme.event_font_size != requested_event_font_size
            or theme.time_font_size != requested_time_font_size
        ),
    }