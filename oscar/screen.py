"""Screen capture helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from oscar import config

if TYPE_CHECKING:
    from PIL.Image import Image


def _annotate_with_grid(image: "Image", interval: int) -> "Image":
    if interval <= 0:
        return image

    try:
        from PIL import ImageDraw, ImageFont
    except ImportError:
        return image

    annotated = image.convert("RGBA")
    draw = ImageDraw.Draw(annotated, "RGBA")
    width, height = annotated.size

    try:
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover - pillow/platform specific
        font = None

    line_color = (0, 128, 255, 110)
    label_fill = (0, 0, 0, 170)
    label_text = (255, 255, 255, 255)

    for x in range(0, width, interval):
        draw.line([(x, 0), (x, height)], fill=line_color, width=1)
        label = str(x)
        text_box = draw.textbbox((0, 0), label, font=font) if font else (0, 0, 24, 10)
        box_width = text_box[2] - text_box[0] + 8
        box_height = text_box[3] - text_box[1] + 4
        draw.rectangle([(x, 0), (min(x + box_width, width), min(box_height, height))], fill=label_fill)
        draw.text((x + 4, 2), label, fill=label_text, font=font)

    for y in range(0, height, interval):
        draw.line([(0, y), (width, y)], fill=line_color, width=1)
        label = str(y)
        text_box = draw.textbbox((0, 0), label, font=font) if font else (0, 0, 24, 10)
        box_width = text_box[2] - text_box[0] + 8
        box_height = text_box[3] - text_box[1] + 4
        draw.rectangle([(0, y), (min(box_width, width), min(y + box_height, height))], fill=label_fill)
        draw.text((4, y + 2), label, fill=label_text, font=font)

    return annotated.convert("RGB")


def capture_screenshot(
    region: tuple[int, int, int, int] | None = None,
) -> tuple["Image", tuple[int, int]]:
    """Capture a screenshot and return the image plus its dimensions."""

    try:
        from mss import mss
    except ImportError as exc:  # pragma: no cover - dependency specific
        raise RuntimeError("mss is required for screen capture.") from exc

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - dependency specific
        raise RuntimeError("Pillow is required for screen capture.") from exc

    with mss() as screenshotter:
        if region is None:
            monitor = screenshotter.monitors[1]
        else:
            left, top, width, height = region
            monitor = {"left": left, "top": top, "width": width, "height": height}

        shot = screenshotter.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        if config.ENABLE_SCREENSHOT_GRID:
            image = _annotate_with_grid(image, config.SCREENSHOT_GRID_INTERVAL)
        return image, (int(shot.width), int(shot.height))
