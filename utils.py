"""Shared validation and formatting helpers."""

import re
from datetime import datetime


def validate_slug(slug: str) -> tuple[bool, str]:
    """Validate an event slug. Returns (is_valid, error_message)."""
    if not slug:
        return False, "Slug is required."
    if len(slug) > 31:
        return False, f"Slug must be at most 31 characters (got {len(slug)})."
    if not slug[0].isalpha():
        return False, "Slug must start with a letter."
    if slug != slug.lower():
        return False, "Slug must be lowercase."
    if not re.match(r"^[a-z][a-z0-9-]*$", slug):
        return False, "Slug may only contain lowercase letters, numbers, and hyphens."
    return True, ""


def format_datetime(value: str | None) -> str:
    """Format an ISO datetime string for display."""
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, AttributeError):
        return str(value)


def slugify_hol_name(name: str) -> str:
    """Derive a valid event slug from a HOL name.

    e.g. "FY26 Azure AI HOL" -> "fy26-azure-ai-hol"
         "2025 Partner HOL"  -> "a2025-partner-hol"
    """
    if not name:
        return ""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    # Slugs must start with a letter
    if slug and not slug[0].isalpha():
        slug = "a" + slug
    # Enforce max length
    slug = slug[:31]
    # Re-strip trailing hyphen that truncation might create
    slug = slug.rstrip("-")
    return slug


def parse_comma_list(text: str) -> list[str]:
    """Parse a comma- or whitespace-delimited string into a list of trimmed strings."""
    if not text.strip():
        return []
    import re
    return [item for item in re.split(r"[,\s]+", text.strip()) if item]
