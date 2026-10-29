import math
from datetime import datetime, timedelta, timezone

SEVERITY_WEIGHTS: dict[str, int] = {
    "CRITICAL": 40_000,
    "HIGH": 20_000,
    "MEDIUM": 10_000,
    "LOW": 0,
}

DEFAULT_SLA_HOURS: dict[str, int] = {
    "CRITICAL": 4,
    "HIGH": 24,
    "MEDIUM": 72,
    "LOW": 168,
}

MAX_SLA_URGENCY_POINTS = 9_999
UPVOTE_WEIGHT = 25


def haversine_distance_meters(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    radius = 6_371_000.0
    phi_a = math.radians(latitude_a)
    phi_b = math.radians(latitude_b)
    delta_phi = math.radians(latitude_b - latitude_a)
    delta_lambda = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2.0) ** 2
    )
    return radius * 2.0 * math.atan2(math.sqrt(value), math.sqrt(1.0 - value))


def normalize_severity(value: str | None) -> str:
    severity = (value or "MEDIUM").strip().upper()
    return severity if severity in SEVERITY_WEIGHTS else "MEDIUM"


def calculate_sla_urgency_points(
    severity: str,
    created_at: datetime,
    now: datetime | None = None,
    sla_hours: int | None = None,
) -> int:
    """Return bounded urgency points based on elapsed share of the complaint SLA."""
    normalized = normalize_severity(severity)
    current = now or datetime.now(timezone.utc)
    created = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    current = current if current.tzinfo else current.replace(tzinfo=timezone.utc)
    allowed_hours = sla_hours or DEFAULT_SLA_HOURS[normalized]
    total_seconds = max(1.0, timedelta(hours=allowed_hours).total_seconds())
    elapsed_ratio = max(0.0, (current - created).total_seconds() / total_seconds)
    return min(MAX_SLA_URGENCY_POINTS, int(elapsed_ratio * MAX_SLA_URGENCY_POINTS))


def calculate_composite_score(
    severity: str,
    upvote_count: int,
    created_at: datetime,
    now: datetime | None = None,
    sla_hours: int | None = None,
) -> int:
    normalized = normalize_severity(severity)
    return (
        SEVERITY_WEIGHTS[normalized]
        + max(0, upvote_count) * UPVOTE_WEIGHT
        + calculate_sla_urgency_points(normalized, created_at, now, sla_hours)
    )


def calculate_sla_deadline(
    severity: str,
    created_at: datetime,
    sla_hours: int | None = None,
) -> datetime:
    normalized = normalize_severity(severity)
    created = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    return created + timedelta(hours=sla_hours or DEFAULT_SLA_HOURS[normalized])
