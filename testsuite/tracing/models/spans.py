"""Span-related data models for distributed tracing"""

from dataclasses import dataclass
from typing import Any

from .logs import LogEntry, _parse_otlp_attributes


@dataclass(frozen=True)
class SpanReference:
    """Represents a reference to another span"""

    ref_type: str  # "CHILD_OF", "FOLLOWS_FROM"
    trace_id: str
    span_id: str


@dataclass(frozen=True)
class Span:  # pylint: disable=too-many-instance-attributes
    """Represents a single span in a distributed trace"""

    name: str
    span_id: str
    trace_id: str
    start_time: int
    duration: int  # Duration in microseconds (must be non-negative)
    attributes: dict[str, Any]
    events: list[LogEntry]
    references: list[SpanReference]
    process_id: str

    def get_attribute(self, key: str, default=None) -> Any:
        """Get attribute value by key"""
        return self.attributes.get(key, default)

    def has_attribute(self, key: str, value: Any = None) -> bool:  # pylint: disable=too-many-return-statements
        """
        Check if span has an attribute with matching value.

        Args:
            key: Attribute key to check
            value: Optional value to match. Matching rules:
                - If attribute value is a list: checks exact membership
                - If both are strings: checks substring match (case-insensitive)
                - If types differ but one is numeric: try type coercion
                - Otherwise: checks equality

        Returns:
            True if attribute exists (and matches value if provided)
        """
        if key not in self.attributes:
            return False
        if value is None:
            return True

        attr_value = self.attributes[key]

        if isinstance(attr_value, list):
            return value in attr_value

        if isinstance(value, str) and isinstance(attr_value, str):
            return str(value).lower() in str(attr_value).lower()

        if value == attr_value:
            return True

        if isinstance(value, (int, float)) and isinstance(attr_value, str):
            try:
                return value == type(value)(attr_value)
            except (ValueError, TypeError):
                return False
        if isinstance(attr_value, (int, float)) and isinstance(value, str):
            try:
                return type(attr_value)(value) == attr_value
            except (ValueError, TypeError):
                return False

        return False

    def get_parent_id(self) -> str | None:
        """Get parent span ID from CHILD_OF reference"""
        for ref in self.references:
            if ref.ref_type == "CHILD_OF":
                return ref.span_id
        return None

    def has_event_field(self, key: str, value: str | None = None) -> bool:
        """Check if any log entry has a field with exact value match"""
        for log_entry in self.events:
            if log_entry.has_field(key, value):
                return True
        return False

    _OTLP_STATUS_NAMES = {1: "OK", 2: "ERROR"}

    @classmethod
    def from_otlp(cls, span_data: dict, trace_id: str, process_id: str) -> "Span":
        """Create Span from OTLP span dict"""
        logs = [LogEntry.from_otlp(event) for event in span_data.get("events", [])]

        references = []
        parent_span_id = span_data.get("parentSpanId", "")
        if parent_span_id:
            references.append(SpanReference(ref_type="CHILD_OF", trace_id=trace_id, span_id=parent_span_id))

        start_nano = int(span_data.get("startTimeUnixNano", "0"))
        end_nano = int(span_data.get("endTimeUnixNano", "0"))

        tags = _parse_otlp_attributes(span_data.get("attributes", []))

        status = span_data.get("status", {})
        status_code = status.get("code", 0)
        if status_code in cls._OTLP_STATUS_NAMES:
            tags.setdefault("otel.status_code", cls._OTLP_STATUS_NAMES[status_code])
        if status_code == 2:
            tags.setdefault("error", True)
        if status.get("message"):
            tags.setdefault("otel.status_description", status["message"])

        return cls(
            name=span_data.get("name", ""),
            span_id=span_data.get("spanId", ""),
            trace_id=trace_id,
            start_time=start_nano // 1000,
            duration=max((end_nano - start_nano) // 1000, 0),
            attributes=tags,
            events=logs,
            references=references,
            process_id=process_id,
        )
