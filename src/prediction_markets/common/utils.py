"""
Common utilities for prediction markets.

Provides standardized parsing and formatting functions that work
across different prediction market exchanges.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


def parse_datetime(value: Any) -> datetime | None:
    """
    Parse various datetime formats to UTC timezone-aware datetime.

    Supported formats:
    - datetime object (with or without timezone)
    - ISO 8601 string: "2026-01-12T17:00:00Z", "2026-01-12T17:00:00+00:00"
    - Unix timestamp (seconds): 1736697600
    - Unix timestamp (milliseconds): 1736697600000
    - Date string: "2026-01-12"

    Returns:
        UTC timezone-aware datetime or None if parsing fails

    Example:
        >>> parse_datetime("2026-01-12T17:00:00Z")
        datetime(2026, 1, 12, 17, 0, 0, tzinfo=timezone.utc)
        >>> parse_datetime(1736697600)
        datetime(2026, 1, 12, 17, 0, 0, tzinfo=timezone.utc)
    """
    if value is None:
        return None

    # Already a datetime
    if isinstance(value, datetime):
        if value.tzinfo is None:
            # Assume UTC if no timezone
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    value_str = str(value).strip()
    if not value_str:
        return None

    # Try ISO format with various timezone representations
    for fmt_suffix in ["Z", "+00:00", ""]:
        try:
            # Handle "Z" suffix (Zulu time = UTC)
            normalized = value_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            pass

    # Try date-only format
    try:
        dt = datetime.strptime(value_str, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        pass

    # Try timestamp (seconds or milliseconds)
    try:
        ts = float(value)
        # If timestamp is too large, it's likely milliseconds
        if ts > 1e12:
            ts = ts / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        pass

    return None


def format_datetime(dt: datetime | None, fmt: str = "iso") -> str | None:
    """
    Format datetime to standardized string.

    Args:
        dt: datetime to format
        fmt: format type
            - "iso": ISO 8601 format (default)
            - "date": Date only (YYYY-MM-DD)
            - "human": Human readable (Jan 12, 2026 5:00 PM UTC)

    Returns:
        Formatted string or None if dt is None

    Example:
        >>> format_datetime(dt, "iso")
        "2026-01-12T17:00:00+00:00"
        >>> format_datetime(dt, "date")
        "2026-01-12"
        >>> format_datetime(dt, "human")
        "Jan 12, 2026 5:00 PM UTC"
    """
    if dt is None:
        return None

    # Ensure UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    if fmt == "iso":
        return dt.isoformat()
    elif fmt == "date":
        return dt.strftime("%Y-%m-%d")
    elif fmt == "human":
        return dt.strftime("%b %d, %Y %I:%M %p UTC")
    else:
        return dt.isoformat()


def parse_decimal(value: Any) -> Decimal | None:
    """
    Parse various numeric formats to Decimal.

    Args:
        value: Value to parse (string, int, float, Decimal)

    Returns:
        Decimal or None if parsing fails
    """
    if value is None:
        return None

    if isinstance(value, Decimal):
        return value

    try:
        # Handle string with commas (e.g., "1,234.56")
        if isinstance(value, str):
            value = value.replace(",", "")
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
