"""Helpers for turning browser-oriented tasks into reliable semantic steps."""

from __future__ import annotations

from datetime import datetime, timedelta
import re
from dataclasses import dataclass


_TIME_PATTERN = re.compile(
    r"\b(?:when(?:\s+(?:the\s+)?time)?\s+(?:hits|reaches|is)|when\s+it(?:'s| is)|at)\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:am|pm))?)\b",
    re.IGNORECASE,
)
_SEARCH_PATTERN = re.compile(
    r"(?:search(?:\s+for)?|look\s+for|look\s+up|find)\s+(?P<query>.+)",
    re.IGNORECASE,
)
_NAVIGATE_PATTERN = re.compile(
    r"(?:go\s+to|goto|visit|navigate\s+to)\s+(?P<target>.+)",
    re.IGNORECASE,
)
_FOLLOW_UP_PATTERN = re.compile(
    r"\b(?:and|then)\s+(?:download|save|click|open|extract|select|choose|pick|share|upload|attach|reply|login|log\s+in|sign\s+in)\b.*$",
    re.IGNORECASE,
)
_NEW_TAB_PATTERN = re.compile(r"\b(?:another|new)\s+tab\b", re.IGNORECASE)
_IMAGE_PATTERN = re.compile(
    r"\b(?:image|images|photo|photos|picture|pictures|wallpaper)\b",
    re.IGNORECASE,
)
_URL_PATTERN = re.compile(r"^(?:https?://)?[a-z0-9][a-z0-9.-]+\.[a-z]{2,}(?:/.*)?$", re.IGNORECASE)
_CURRENT_TIME_PATTERN = re.compile(
    r"\b(?:(?:what(?:'s| is)?|tell me|show me)\s+(?:the\s+)?)?(?:current\s+time|time\s+now|time\b)\??$",
    re.IGNORECASE,
)
_CURRENT_DATE_PATTERN = re.compile(
    r"\b(?:(?:what(?:'s| is)?|tell me|show me)\s+(?:the\s+)?)?(?:current\s+date|date\s+today|today'?s\s+date|what\s+date\s+is\s+it|date\b)\??$",
    re.IGNORECASE,
)
_BROWSER_OPEN_PATTERN = re.compile(
    r"^(?:open|launch|start|go\s+to|goto)\s+(?P<body>.+)$",
    re.IGNORECASE,
)
_BROWSER_NAME_PATTERN = re.compile(
    r"\b(?P<browser>google chrome|chrome|microsoft edge|edge|brave|firefox)\b",
    re.IGNORECASE,
)
_PROFILE_AFTER_BROWSER_PATTERN = re.compile(
    r"\b(?:and\s+)?(?:use\s+)?(?P<profile>.+?)\s+profile\b",
    re.IGNORECASE,
)
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "browser",
    "device",
    "download",
    "for",
    "from",
    "google",
    "image",
    "images",
    "in",
    "my",
    "of",
    "on",
    "photo",
    "photos",
    "picture",
    "pictures",
    "please",
    "save",
    "search",
    "tab",
    "the",
    "to",
    "wallpaper",
}
_TOKEN_NORMALIZATIONS = {
    "pomerian": "pomeranian",
    "pomarian": "pomeranian",
}
_BROWSER_APP_NAMES = {
    "google chrome",
    "chrome",
    "browser",
    "microsoft edge",
    "edge",
    "brave",
    "firefox",
}
_KNOWN_NAVIGATION_ALIASES = {
    "github": "https://github.com",
    "github.com": "https://github.com",
    "whatsapp web": "https://web.whatsapp.com",
    "my whatsapp web": "https://web.whatsapp.com",
    "whatsapp": "https://web.whatsapp.com",
}


@dataclass(frozen=True)
class BrowserRequest:
    """A parsed request for a specific desktop browser and optional profile."""

    browser_name: str
    profile_name: str | None = None


def extract_wait_until_time(task: str) -> str | None:
    """Return a time-of-day trigger from a natural-language task."""

    target = extract_wait_until_datetime(task)
    if target is None:
        return None
    return target.strftime("%H:%M:%S")


def extract_wait_until_datetime(
    task: str,
    *,
    reference_time: str | None = None,
) -> datetime | None:
    """Return the intended local wait target as a concrete datetime.

    If the requested clock time is only a few seconds in the past, keep that
    same-day timestamp so the planner can proceed immediately instead of waiting
    until tomorrow.
    """

    match = _TIME_PATTERN.search(" ".join(task.strip().split()))
    if match is None:
        return None

    parsed = _parse_time_token(match.group("time"))
    if parsed is None:
        return None

    reference = _parse_reference_time(reference_time)
    target = reference.replace(
        hour=parsed.hour,
        minute=parsed.minute,
        second=parsed.second,
        microsecond=0,
    )
    if target < reference and (reference - target) > timedelta(minutes=5):
        target += timedelta(days=1)
    return target


def normalize_url(url: str) -> str:
    """Normalize a user-provided URL-like value."""

    cleaned = url.strip().strip("\"'")
    if not cleaned:
        return cleaned
    if re.match(r"^[a-z][a-z0-9+\-.]*://", cleaned, re.IGNORECASE):
        return cleaned
    if _URL_PATTERN.match(cleaned):
        return f"https://{cleaned}"
    return cleaned


def extract_navigation_target(task: str) -> str | None:
    """Return a normalized navigation target from the task, if present."""

    remaining = " ".join(task.strip().split())
    while remaining:
        match = _NAVIGATE_PATTERN.search(remaining)
        if match is None:
            return None

        raw_target = str(match.group("target") or "")
        candidate = re.split(
            r"\b(?:and|then|after)\b",
            raw_target,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" ,.")
        if not candidate:
            remaining = raw_target
            continue

        lowered_candidate = " ".join(candidate.lower().split())
        if lowered_candidate in _KNOWN_NAVIGATION_ALIASES:
            return _KNOWN_NAVIGATION_ALIASES[lowered_candidate]

        normalized = normalize_url(candidate)
        if not normalized or is_browser_app_name(normalized):
            remaining = raw_target
            continue
        if re.match(r"^[a-z][a-z0-9+\-.]*://", normalized, re.IGNORECASE):
            return normalized
        if _URL_PATTERN.match(normalized):
            return normalized
        remaining = raw_target
    return None


def simplify_search_query(query: str, *, aggressive: bool = False) -> str:
    """Collapse noisy search instructions into short, stable keyword queries."""

    cleaned = " ".join(query.strip().split()).strip("\"'")
    cleaned = _FOLLOW_UP_PATTERN.sub("", cleaned)
    cleaned = _NEW_TAB_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"[^\w\s.+#-]", " ", cleaned)
    tokens = [token for token in cleaned.lower().split() if token]
    filtered = [
        _TOKEN_NORMALIZATIONS.get(token, token)
        for token in tokens
        if token not in _STOP_WORDS
    ]
    if not filtered:
        filtered = tokens
    if aggressive and len(filtered) > 2:
        filtered = filtered[-2:]
    elif len(filtered) > 5:
        filtered = filtered[:5]
    return " ".join(filtered).strip()


def extract_search_query(task: str, *, aggressive: bool = False) -> str | None:
    """Extract and simplify the search intent from a task."""

    match = _SEARCH_PATTERN.search(" ".join(task.strip().split()))
    if match is None:
        return None
    query = simplify_search_query(match.group("query"), aggressive=aggressive)
    return query or None


def task_requires_new_tab(task: str) -> bool:
    """Return whether the task explicitly requests another browser tab."""

    return _NEW_TAB_PATTERN.search(task) is not None


def task_requests_images(task: str) -> bool:
    """Return whether the task explicitly asks for image-style results."""

    return _IMAGE_PATTERN.search(task) is not None


def task_requests_current_time(task: str) -> bool:
    """Return whether the user is explicitly asking for the current local time."""

    normalized = " ".join(task.strip().split())
    lowered = normalized.lower()
    if "last time" in lowered or "next time" in lowered:
        return False
    return _CURRENT_TIME_PATTERN.fullmatch(normalized) is not None


def task_requests_current_date(task: str) -> bool:
    """Return whether the user is explicitly asking for the current local date."""

    normalized = " ".join(task.strip().split())
    lowered = normalized.lower()
    if "update" in lowered or "due date" in lowered or "date range" in lowered:
        return False
    return _CURRENT_DATE_PATTERN.fullmatch(normalized) is not None


def extract_browser_request(task: str) -> BrowserRequest | None:
    """Parse a desktop browser launch request and optional named profile.

    Examples:
    - ``open chrome and goto github.com`` -> chrome, no profile
    - ``open work chrome and goto github.com`` -> chrome, profile work
    """

    normalized = " ".join(task.strip().split())
    prefix_match = _BROWSER_OPEN_PATTERN.match(normalized)
    if prefix_match is None:
        return None

    body = str(prefix_match.group("body") or "").strip()
    browser_match = _BROWSER_NAME_PATTERN.search(body)
    if browser_match is None:
        return None

    browser_name = " ".join(str(browser_match.group("browser") or "").strip().split())
    profile_name = _extract_profile_name(body, browser_match.start(), browser_match.end())
    if not browser_name:
        return None
    return BrowserRequest(browser_name=browser_name, profile_name=profile_name)


def is_browser_app_name(value: str) -> bool:
    """Return whether a value is a browser app reference rather than a URL."""

    normalized = " ".join(str(value or "").strip().lower().split())
    return normalized in _BROWSER_APP_NAMES


def _parse_reference_time(reference_time: str | None) -> datetime:
    if reference_time:
        try:
            return datetime.fromisoformat(reference_time)
        except ValueError:
            pass
    return datetime.now().astimezone()


def _parse_time_token(raw_value: str) -> datetime | None:
    cleaned = " ".join(raw_value.strip().lower().split())
    formats = ("%I:%M %p", "%I:%M:%S %p", "%H:%M", "%H:%M:%S")
    for format_string in formats:
        try:
            return datetime.strptime(cleaned, format_string)
        except ValueError:
            continue
    return None


def _extract_profile_name(body: str, browser_start: int, browser_end: int) -> str | None:
    after_browser = body[browser_end:]
    match = _PROFILE_AFTER_BROWSER_PATTERN.search(after_browser)
    if match is not None:
        profile = " ".join(str(match.group("profile") or "").strip().split())
        return profile or None

    before_browser = body[:browser_start].strip()
    if not before_browser:
        return None
    profile = re.sub(
        r"^(?:and|then|use|with|the|my)\b",
        "",
        before_browser,
        flags=re.IGNORECASE,
    ).strip(" ,.")
    return profile or None
