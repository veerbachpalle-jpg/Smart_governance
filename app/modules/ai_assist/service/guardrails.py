import re
import time
from typing import Any


class CircuitBreakerOpenError(Exception):
    """Raised when the AI provider circuit breaker is OPEN due to repeated failures."""

    pass


class CircuitBreaker:
    """In-memory circuit breaker protecting the system from cascading AI provider outages."""

    def __init__(self, failure_threshold: int = 3, reset_timeout_seconds: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds
        self.consecutive_failures = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.last_failure_time: float | None = None

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.state = "CLOSED"
        self.last_failure_time = None

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.last_failure_time = time.monotonic()
        if self.consecutive_failures >= self.failure_threshold:
            self.state = "OPEN"

    def can_execute(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if self.last_failure_time is not None:
                elapsed = time.monotonic() - self.last_failure_time
                if elapsed >= self.reset_timeout_seconds:
                    self.state = "HALF_OPEN"
                    return True
            return False
        if self.state == "HALF_OPEN":
            return True
        return False


# Global circuit breaker instance
ai_circuit_breaker = CircuitBreaker()


def redact_pii(text: str) -> str:
    """Scans and redacts sensitive PII (emails, Indian phone numbers, Aadhaar IDs) before LLM egress."""
    # 1. Email addresses
    email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    redacted = re.sub(email_pattern, "[REDACTED_EMAIL]", text)

    # 2. Aadhaar numbers (12 digits, grouped as 4-4-4 or contiguous)
    aadhaar_pattern = r"\b[2-9]\d{3}[\s\-]?\d{4}[\s\-]?\d{4}\b"
    redacted = re.sub(aadhaar_pattern, "[REDACTED_AADHAAR]", redacted)

    # 3. Phone numbers (+91, 0, or 10-digit Indian mobile starting with 6-9)
    phone_pattern = r"(?:\+91[\-\s]?|91[\-\s]?|0)?[6-9]\d{4}[\-\s]?\d{5}\b"
    redacted = re.sub(phone_pattern, "[REDACTED_PHONE]", redacted)

    return redacted


def sanitize_and_delimit_untrusted_input(title: str, description: str) -> str:
    """Wraps untrusted citizen inputs in XML-style boundary tags, escaping escape sequences."""
    clean_title = redact_pii(title).replace("</untrusted_citizen_submission>", "[ESCAPED_TAG]")
    clean_desc = redact_pii(description).replace("</untrusted_citizen_submission>", "[ESCAPED_TAG]")

    return (
        "<untrusted_citizen_submission>\n"
        f"<title>{clean_title}</title>\n"
        f"<description>{clean_desc}</description>\n"
        "</untrusted_citizen_submission>"
    )


def validate_root_cause_guardrail(parsed_output: dict[str, Any]) -> dict[str, Any]:
    """Ensures reported_facts never assert a root cause and inferences are properly flagged."""
    reported_facts = parsed_output.get("reported_facts", [])
    inferences = parsed_output.get("inferences", [])
    causes = parsed_output.get("potential_root_causes", [])

    forbidden_cause_markers = [
        "root cause is",
        "definitely caused by",
        "proven cause",
        "the culprit is",
        "the reason why",
    ]

    clean_facts = []
    for fact in reported_facts:
        f_lower = fact.lower()
        if any(marker in f_lower for marker in forbidden_cause_markers):
            # Demote any cause statement to inferences as hypothesis
            inferences.append(f"Unverified hypothesis: {fact}")
        else:
            clean_facts.append(fact)

    clean_causes = []
    hypothesis_markers = [
        "hypothesis",
        "possible",
        "potential",
        "suspected",
        "unverified",
        "inferred",
        "likely",
    ]
    for cause in causes:
        if not any(marker in cause.lower() for marker in hypothesis_markers):
            clean_causes.append(f"Unverified hypothesis: {cause}")
        else:
            clean_causes.append(cause)

    parsed_output["reported_facts"] = clean_facts
    parsed_output["inferences"] = inferences
    parsed_output["potential_root_causes"] = clean_causes
    return parsed_output
