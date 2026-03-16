"""Gemini client helpers for OSCAR."""

from __future__ import annotations

import io
import json
import sys
from typing import Any

from oscar import config
from oscar.prompt_builder import SYSTEM_PROMPT


RECOMMENDED_MODEL = "gemini-2.5-flash"
CLICK_REFINEMENT_SYSTEM_PROMPT = """You refine one mouse target on a screenshot crop.
Return only valid JSON.
Do not describe anything outside JSON.
Coordinates must always be full-screen absolute coordinates, never crop-relative coordinates."""


class GeminiResponseError(RuntimeError):
    """Raised when Gemini cannot produce a usable action payload."""


def _load_genai():
    try:
        import google.genai as genai
    except ImportError:
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise RuntimeError(
                "A Gemini SDK is not installed for this Python interpreter "
                f"({sys.executable}). Install it in the active environment with "
                "'python -m pip install -r requirements.txt' or "
                "'python -m pip install google-genai'."
            ) from exc
    return genai


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"


def _build_request_error_message(sdk_name: str, model_name: str, exc: Exception) -> str:
    base_message = f"Gemini request failed ({sdk_name}): {_format_exception(exc)}"
    lowered = str(exc).lower()
    if "404" in lowered and "not_found" in lowered and "model" in lowered:
        return (
            f"{base_message}. The configured GEMINI_MODEL '{model_name}' is not available. "
            f"Try GEMINI_MODEL={RECOMMENDED_MODEL}."
        )
    return base_message


def _build_legacy_image_part(screenshot: Any) -> dict[str, bytes | str]:
    buffer = io.BytesIO()
    screenshot.save(buffer, format="PNG")
    return {"mime_type": "image/png", "data": buffer.getvalue()}


def _build_new_sdk_config(genai: Any, *, system_prompt: str, temperature: float) -> Any:
    types_module = getattr(genai, "types", None)
    if types_module is not None and hasattr(types_module, "GenerateContentConfig"):
        return types_module.GenerateContentConfig(
            systemInstruction=system_prompt,
            temperature=temperature,
        )

    return {
        "systemInstruction": system_prompt,
        "temperature": temperature,
    }


def _build_model_backend(
    genai: Any,
    *,
    api_key: str,
    model_name: str,
    temperature: float,
    system_prompt: str,
):
    if hasattr(genai, "Client"):
        try:
            client = genai.Client(api_key=api_key)
            generation_config = _build_new_sdk_config(
                genai,
                system_prompt=system_prompt,
                temperature=temperature,
            )
        except Exception as exc:
            raise GeminiResponseError(
                f"Failed to initialize the Gemini client (google-genai): {_format_exception(exc)}"
            ) from exc

        return (
            "google-genai",
            lambda prompt, screenshot: client.models.generate_content(
                model=model_name,
                contents=[prompt, screenshot],
                config=generation_config,
            ),
        )

    if hasattr(genai, "GenerativeModel"):
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=system_prompt,
                generation_config={"temperature": temperature},
            )
        except Exception as exc:
            raise GeminiResponseError(
                "Failed to initialize the Gemini client (google-generativeai): "
                f"{_format_exception(exc)}"
            ) from exc

        return (
            "google-generativeai",
            lambda prompt, screenshot: model.generate_content(
                [prompt, _build_legacy_image_part(screenshot)]
            ),
        )

    raise GeminiResponseError("No supported Gemini SDK API was found.")


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return text

    parts: list[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                parts.append(part_text)

    return "".join(parts)


def _extract_json_text(response_text: str) -> str:
    start_index = response_text.find("{")
    end_index = response_text.rfind("}")
    if start_index == -1 or end_index == -1 or end_index < start_index:
        raise ValueError("Gemini response did not contain a JSON object.")
    return response_text[start_index : end_index + 1]


def _parse_response_text(response_text: str) -> dict[str, Any]:
    return json.loads(_extract_json_text(response_text))


def _generate_json_response(
    generate_content,
    *,
    prompt: str,
    screenshot: Any,
    retries: int,
) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt_index in range(retries + 1):
        attempt_prompt = prompt
        if attempt_index > 0:
            attempt_prompt = (
                f"{prompt}\n\nThe previous response was invalid. Return only one valid JSON object."
            )

        response = generate_content(attempt_prompt, screenshot)
        response_text = _extract_text(response)
        try:
            return _parse_response_text(response_text)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc

    raise GeminiResponseError(
        f"Gemini returned invalid JSON after {retries + 1} attempt(s)."
    ) from last_error


def ask_gemini(
    screenshot: Any,
    prompt: str,
    *,
    model_name: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.2,
    retries: int = 1,
) -> dict[str, Any]:
    """Send the current screenshot and prompt to Gemini and parse the JSON reply."""

    genai = _load_genai()
    resolved_api_key = api_key or config.require_api_key()
    resolved_model = model_name or config.GEMINI_MODEL
    sdk_name, generate_content = _build_model_backend(
        genai,
        api_key=resolved_api_key,
        model_name=resolved_model,
        temperature=temperature,
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        return _generate_json_response(
            generate_content,
            prompt=prompt,
            screenshot=screenshot,
            retries=retries,
        )
    except GeminiResponseError:
        raise
    except Exception as exc:
        raise GeminiResponseError(
            _build_request_error_message(sdk_name, resolved_model, exc)
        ) from exc


def _annotate_click_candidate(
    crop: Any,
    *,
    marker_x: int,
    marker_y: int,
    left: int,
    top: int,
    scale_x: float,
    scale_y: float,
) -> Any:
    try:
        from PIL import ImageDraw, ImageFont

        if not hasattr(crop, "copy"):
            return crop

        annotated = crop.copy()
        draw = ImageDraw.Draw(annotated, "RGBA")
        width, height = annotated.size
        interval = max(48, min(120, int(min(width, height) / 4)))

        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        line_color = (0, 128, 255, 90)
        label_fill = (0, 0, 0, 170)
        label_text = (255, 255, 255, 255)

        for x in range(0, width, interval):
            absolute_x = left + int(round(x / max(scale_x, 0.001)))
            draw.line([(x, 0), (x, height)], fill=line_color, width=1)
            label = str(absolute_x)
            text_box = draw.textbbox((0, 0), label, font=font) if font else (0, 0, 30, 12)
            box_width = text_box[2] - text_box[0] + 8
            box_height = text_box[3] - text_box[1] + 4
            draw.rectangle([(x, 0), (min(x + box_width, width), min(box_height, height))], fill=label_fill)
            draw.text((x + 4, 2), label, fill=label_text, font=font)

        for y in range(0, height, interval):
            absolute_y = top + int(round(y / max(scale_y, 0.001)))
            draw.line([(0, y), (width, y)], fill=line_color, width=1)
            label = str(absolute_y)
            text_box = draw.textbbox((0, 0), label, font=font) if font else (0, 0, 30, 12)
            box_width = text_box[2] - text_box[0] + 8
            box_height = text_box[3] - text_box[1] + 4
            draw.rectangle([(0, y), (min(box_width, width), min(y + box_height, height))], fill=label_fill)
            draw.text((4, y + 2), label, fill=label_text, font=font)

        radius = 10
        draw.ellipse(
            (marker_x - radius, marker_y - radius, marker_x + radius, marker_y + radius),
            outline="red",
            width=3,
        )
        draw.line((marker_x - 18, marker_y, marker_x + 18, marker_y), fill="red", width=3)
        draw.line((marker_x, marker_y - 18, marker_x, marker_y + 18), fill="red", width=3)
        return annotated
    except Exception:
        return crop


def _refine_click_coordinates_once(
    screenshot: Any,
    action: dict[str, Any],
    *,
    original_x: int,
    original_y: int,
    current_x: int,
    current_y: int,
    radius: int,
    overall_max_shift: int,
    generate_content,
    retries: int,
) -> tuple[int, int, str | None] | None:
    width, height = screenshot.size
    left = max(0, current_x - radius)
    top = max(0, current_y - radius)
    right = min(width, current_x + radius)
    bottom = min(height, current_y + radius)

    if right - left < 20 or bottom - top < 20:
        return None

    crop_width = max(right - left, 1)
    crop_height = max(bottom - top, 1)
    scale_x = 1.0
    scale_y = 1.0
    crop = screenshot.crop((left, top, right, bottom))
    if hasattr(crop, "resize"):
        try:
            from PIL import Image

            resized_width = crop.size[0] * 2
            resized_height = crop.size[1] * 2
            crop = crop.resize((resized_width, resized_height), Image.Resampling.LANCZOS)
            scale_x = resized_width / crop_width
            scale_y = resized_height / crop_height
        except Exception:
            pass

    marker_x = int(round((current_x - left) * scale_x))
    marker_y = int(round((current_y - top) * scale_y))
    crop = _annotate_click_candidate(
        crop,
        marker_x=marker_x,
        marker_y=marker_y,
        left=left,
        top=top,
        scale_x=scale_x,
        scale_y=scale_y,
    )

    prompt = (
        "Refine the proposed mouse target shown in this zoomed crop.\n"
        "A red crosshair marks the current proposed click point. Blue grid labels show absolute full-screen coordinates.\n"
        f"Full screenshot size: {width}x{height}.\n"
        f"Crop bounds in full-screen coordinates: left={left}, top={top}, right={right}, bottom={bottom}.\n"
        f"Current proposed coordinates: ({current_x}, {current_y}).\n"
        f"Original action: {json.dumps(action, ensure_ascii=True)}\n"
        "Stay on the same UI element implied by the original action. "
        "Prefer the center of the primary clickable surface. "
        "Do not switch to a nearby badge, text label, icon, or neighboring control. "
        "Return only JSON with this shape: "
        '{"x": 0, "y": 0, "reasoning": "..."}. '
        "Coordinates must be absolute full-screen coordinates inside the crop bounds. "
        "If the crop does not clearly show a better point, return the current coordinates."
    )

    refined = _generate_json_response(
        generate_content,
        prompt=prompt,
        screenshot=crop,
        retries=retries,
    )

    refined_x = int(refined.get("x", current_x))
    refined_y = int(refined.get("y", current_y))
    if not (left <= refined_x < right and top <= refined_y < bottom):
        return None

    per_pass_max_shift = max(18, min(int(config.CLICK_REFINEMENT_MAX_SHIFT), max(18, radius // 5)))
    if abs(refined_x - current_x) > per_pass_max_shift or abs(refined_y - current_y) > per_pass_max_shift:
        return None
    if abs(refined_x - original_x) > overall_max_shift or abs(refined_y - original_y) > overall_max_shift:
        return None

    refinement_reason = str(refined.get("reasoning", "")).strip() or None
    return refined_x, refined_y, refinement_reason


def refine_click_action(
    screenshot: Any,
    action: dict[str, Any],
    *,
    model_name: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.0,
    retries: int = 0,
) -> dict[str, Any]:
    """Refine a click coordinate by zooming into the candidate area."""

    if not config.ENABLE_CLICK_REFINEMENT:
        return action
    if action.get("action") not in {"click", "double_click", "right_click"}:
        return action
    if not hasattr(screenshot, "crop") or not hasattr(screenshot, "size"):
        return action

    original_x = int(action.get("x", 0))
    original_y = int(action.get("y", 0))
    base_radius = max(int(config.CLICK_REFINEMENT_RADIUS), 40)

    genai = _load_genai()
    resolved_api_key = api_key or config.require_api_key()
    resolved_model = model_name or config.GEMINI_MODEL
    _sdk_name, generate_content = _build_model_backend(
        genai,
        api_key=resolved_api_key,
        model_name=resolved_model,
        temperature=temperature,
        system_prompt=CLICK_REFINEMENT_SYSTEM_PROMPT,
    )

    current_x = original_x
    current_y = original_y
    overall_max_shift = max(18, min(int(config.CLICK_REFINEMENT_MAX_SHIFT), max(18, base_radius // 5)))
    refinement_notes: list[str] = []

    for radius in (base_radius, max(base_radius // 2, 60)):
        try:
            refined = _refine_click_coordinates_once(
                screenshot,
                action,
                original_x=original_x,
                original_y=original_y,
                current_x=current_x,
                current_y=current_y,
                radius=radius,
                overall_max_shift=overall_max_shift,
                generate_content=generate_content,
                retries=retries,
            )
        except Exception:
            break

        if refined is None:
            continue

        refined_x, refined_y, refinement_reason = refined
        current_x = refined_x
        current_y = refined_y
        if refinement_reason:
            refinement_notes.append(refinement_reason)

    if current_x == original_x and current_y == original_y and not refinement_notes:
        return action

    updated = dict(action)
    updated["x"] = current_x
    updated["y"] = current_y
    if refinement_notes:
        updated["reasoning"] = f"{action['reasoning']} Refined target: {' | '.join(refinement_notes[:2])}"
    return updated




