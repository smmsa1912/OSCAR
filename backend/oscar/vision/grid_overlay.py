"""10×10 screenshot grid overlay for vision-based coordinate fallback.

When UIA semantic targeting and Set-of-Mark annotations both fail, the planner
can reference grid cells (A1..J10) instead of raw pixel coordinates. The LLM
tokenizes alphanumeric row/column labels far more reliably than doing mental
arithmetic on a 100-cell numeric grid.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from oscar import config

if TYPE_CHECKING:
    from PIL.Image import Image


def _grid_dimensions() -> tuple[int, int]:
    """Return (rows, cols) from config, clamped to sensible bounds."""
    rows = max(min(int(getattr(config, "GRID_ROWS", 10)), 26), 2)
    cols = max(min(int(getattr(config, "GRID_COLS", 10)), 26), 2)
    return rows, cols


def overlay_grid(
    image: "Image",
    *,
    rows: int | None = None,
    cols: int | None = None,
) -> "Image":
    """Draw a labeled alphanumeric grid over the screenshot.

    Each cell is labeled with a row letter (A–J) and column number (1–10),
    producing labels like A1, B5, J10. The grid uses semi-transparent green
    lines so the underlying screenshot remains visible.
    """

    try:
        from PIL import ImageDraw, ImageFont
    except ImportError:
        return image

    grid_rows, grid_cols = _grid_dimensions()
    rows = rows or grid_rows
    cols = cols or grid_cols

    annotated = image.copy().convert("RGBA")
    draw = ImageDraw.Draw(annotated, "RGBA")
    width, height = annotated.size
    cell_w = width // cols
    cell_h = height // rows

    try:
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover
        font = None

    line_color = (0, 255, 0, 100)
    label_bg = (0, 0, 0, 120)
    label_fg = (0, 255, 0, 220)

    # Draw grid lines
    for r in range(1, rows):
        y = r * cell_h
        draw.line([(0, y), (width, y)], fill=line_color, width=1)
    for c in range(1, cols):
        x = c * cell_w
        draw.line([(x, 0), (x, height)], fill=line_color, width=1)

    # Label each cell
    for r in range(rows):
        for c in range(cols):
            label = f"{chr(65 + r)}{c + 1}"
            x0 = c * cell_w
            y0 = r * cell_h

            text_box = (
                draw.textbbox((0, 0), label, font=font) if font else (0, 0, 16, 10)
            )
            tw = text_box[2] - text_box[0] + 6
            th = text_box[3] - text_box[1] + 4

            draw.rectangle(
                [(x0 + 2, y0 + 2), (x0 + 2 + tw, y0 + 2 + th)],
                fill=label_bg,
            )
            draw.text((x0 + 5, y0 + 3), label, fill=label_fg, font=font)

    return annotated.convert("RGB")


def grid_cell_to_pixel(
    cell: str,
    *,
    screen_width: int,
    screen_height: int,
    rows: int | None = None,
    cols: int | None = None,
) -> tuple[int, int]:
    """Convert a grid cell label like 'B3' to the center pixel coordinate.

    Parameters
    ----------
    cell:
        Alphanumeric cell reference, e.g. "A1", "C5", "J10".
    screen_width, screen_height:
        The actual screen dimensions in pixels.

    Returns
    -------
    (cx, cy): center pixel of the requested grid cell.
    """

    grid_rows, grid_cols = _grid_dimensions()
    rows = rows or grid_rows
    cols = cols or grid_cols

    cell = cell.strip().upper()
    if len(cell) < 2 or not cell[0].isalpha():
        raise ValueError(f"Invalid grid cell reference: {cell!r}")

    row_char = cell[0]
    try:
        col_num = int(cell[1:]) - 1
    except ValueError as exc:
        raise ValueError(f"Invalid grid cell reference: {cell!r}") from exc

    row_idx = ord(row_char) - ord("A")
    if row_idx < 0 or row_idx >= rows:
        raise ValueError(
            f"Row '{row_char}' out of range (A–{chr(64 + rows)}) for {rows}-row grid."
        )
    if col_num < 0 or col_num >= cols:
        raise ValueError(
            f"Column {col_num + 1} out of range (1–{cols}) for {cols}-column grid."
        )

    cell_w = screen_width // cols
    cell_h = screen_height // rows
    cx = col_num * cell_w + cell_w // 2
    cy = row_idx * cell_h + cell_h // 2
    return cx, cy


def pixel_to_grid_cell(
    x: int,
    y: int,
    *,
    screen_width: int,
    screen_height: int,
    rows: int | None = None,
    cols: int | None = None,
) -> str:
    """Convert a pixel coordinate to the nearest grid cell label."""

    grid_rows, grid_cols = _grid_dimensions()
    rows = rows or grid_rows
    cols = cols or grid_cols

    cell_w = max(screen_width // cols, 1)
    cell_h = max(screen_height // rows, 1)
    col_idx = min(max(x // cell_w, 0), cols - 1)
    row_idx = min(max(y // cell_h, 0), rows - 1)
    return f"{chr(65 + row_idx)}{col_idx + 1}"
