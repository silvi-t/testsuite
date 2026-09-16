"""Log-related data models for distributed tracing."""

import json
from dataclasses import dataclass
from typing import Any


def _extract_otlp_value(attr_value: dict) -> Any:
    """Extract typed value from OTLP attribute value wrapper"""
    if "stringValue" in attr_value:
        value = attr_value["stringValue"]
        stripped = value.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                pass
        return value
    if "intValue" in attr_value:
        return int(attr_value["intValue"])
    if "boolValue" in attr_value:
        return attr_value["boolValue"]
    if "doubleValue" in attr_value:
        return attr_value["doubleValue"]
    if "arrayValue" in attr_value:
        return [_extract_otlp_value(v) for v in attr_value["arrayValue"].get("values", [])]
    return str(attr_value)


def _parse_otlp_attributes(attributes: list[dict]) -> dict[str, Any]:
    """Convert OTLP attributes list to a dict, skipping empty keys and duplicates"""
    result = {}
    for attr in attributes:
        key = attr.get("key", "").strip()
        if not key or key in result:
            continue
        result[key] = _extract_otlp_value(attr.get("value", {}))
    return result


@dataclass(frozen=True)
class LogField:
    """Represents a single field in a span log entry"""

    key: str
    value: str
    type: str


@dataclass(frozen=True)
class LogEntry:
    """Represents a log entry in a span"""

    timestamp: int
    fields: list[LogField]

    @classmethod
    def from_otlp(cls, event_data: dict) -> "LogEntry":
        """Create LogEntry from OTLP event dict"""
        fields = [LogField(key="event", value=event_data.get("name", ""), type="string")]
        for attr in event_data.get("attributes", []):
            key = attr.get("key", "").strip()
            if not key:
                continue
            fields.append(LogField(key=key, value=str(_extract_otlp_value(attr.get("value", {}))), type="string"))
        return cls(timestamp=int(event_data.get("timeUnixNano", "0")) // 1000, fields=fields)

    def get_field(self, key: str) -> str | None:
        """Get field value by key. Returns first match if multiple fields have same key"""
        for field in self.fields:
            if field.key == key:
                return field.value
        return None

    def has_field(self, key: str, value: str | None = None) -> bool:
        """Check if log entry has a field with exact value match"""
        field_value = self.get_field(key)
        if field_value is None:
            return False
        if value is None:
            return True
        return value == field_value
