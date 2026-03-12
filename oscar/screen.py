"""Screen capture helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image


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
        return image, (int(shot.width), int(shot.height))
