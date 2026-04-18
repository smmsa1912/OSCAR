"""Screen capture helpers with Set-of-Mark annotations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from oscar import config
from oscar.ui_automation import capture_active_window_controls
from oscar.vision.grid_overlay import overlay_grid

if TYPE_CHECKING:
    from PIL.Image import Image


def _annotate_with_grid(
    image: "Image",
    controls: list[dict[str, Any]],
    *,
    origin: tuple[int, int],
) -> "Image":
    """Overlay numbered boxes on actionable controls instead of edge rulers."""

    if not controls:
        return image

    try:
        from PIL import ImageDraw, ImageFont
    except ImportError:
        return image

    annotated = image.convert("RGBA")
    draw = ImageDraw.Draw(annotated, "RGBA")
    width, height = annotated.size
    origin_left, origin_top = origin

    try:
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover - pillow/platform specific
        font = None

    box_fill = (255, 0, 255, 64)
    box_outline = (255, 0, 255, 255)  # Bright Magenta
    label_fill = (255, 0, 255, 255)   # Match label background to the box
    label_text = (0, 0, 0, 255)

    for control in controls:
        if not control.get("actionable"):
            continue

        try:
            left = int(control.get("left", 0)) - origin_left
            top = int(control.get("top", 0)) - origin_top
            right = int(control.get("right", 0)) - origin_left
            bottom = int(control.get("bottom", 0)) - origin_top
            element_id = int(control.get("element_id", 0))
        except Exception:
            continue

        if element_id <= 0:
            continue
        if right <= 0 or bottom <= 0 or left >= width or top >= height:
            continue

        clipped_left = max(left, 0)
        clipped_top = max(top, 0)
        clipped_right = min(right, width)
        clipped_bottom = min(bottom, height)
        if clipped_right <= clipped_left or clipped_bottom <= clipped_top:
            continue

        draw.rectangle(
            [(clipped_left, clipped_top), (clipped_right, clipped_bottom)],
            fill=box_fill,
            outline=box_outline,
            width=2,
        )

        label = str(element_id)
        text_box = (
            draw.textbbox((0, 0), label, font=font) if font else (0, 0, 18, 10)
        )
        label_width = text_box[2] - text_box[0] + 10
        label_height = text_box[3] - text_box[1] + 6
        label_left = clipped_left
        label_top = max(clipped_top - label_height, 0)
        draw.rectangle(
            [
                (label_left, label_top),
                (min(label_left + label_width, width), min(label_top + label_height, height)),
            ],
            fill=label_fill,
        )
        draw.text((label_left + 5, label_top + 3), label, fill=label_text, font=font)

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
            controls = capture_active_window_controls(limit=40)
            image = _annotate_with_grid(
                image,
                controls,
                origin=(int(monitor["left"]), int(monitor["top"])),
            )
            # Layer the alphanumeric grid on top of Set-of-Mark annotations
            image = overlay_grid(image)
        return image, (int(shot.width), int(shot.height))


def capture_screenshot_with_grid(
    region: tuple[int, int, int, int] | None = None,
) -> tuple["Image", tuple[int, int]]:
    """Capture a screenshot with only the A1..J10 grid overlay (no Set-of-Mark).

    Use this when the planner needs a clean grid reference without UIA control
    annotations cluttering the image.
    """

    try:
        from mss import mss
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("mss is required for screen capture.") from exc

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Pillow is required for screen capture.") from exc

    with mss() as screenshotter:
        if region is None:
            monitor = screenshotter.monitors[1]
        else:
            left, top, width, height = region
            monitor = {"left": left, "top": top, "width": width, "height": height}

        shot = screenshotter.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        image = overlay_grid(image)
        return image, (int(shot.width), int(shot.height))
