"""Trace-related data models for distributed tracing"""

from dataclasses import dataclass
from typing import Any, Callable

from .logs import _parse_otlp_attributes
from .spans import Span


@dataclass(frozen=True)
class Trace:
    """
    Represents a distributed trace with multiple spans.

    Note: Frozen to prevent accidental modification. Internal collections (spans,
    processes) should not be modified after creation.
    """

    trace_id: str
    spans: list[Span]
    processes: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict) -> "Trace":
        """Create Trace from Jaeger API response dict"""
        spans = [Span.from_dict(span_data) for span_data in data.get("spans", [])]
        return cls(
            trace_id=data.get("traceID", ""),
            spans=spans,
            processes=data.get("processes", {}),
        )

    def filter_spans(self, *predicates: Callable[[Span], bool]) -> list[Span]:
        """
        Filter spans using one or more predicates.

        All predicates must return True for a span to be included.
        Use Span properties and Python operators directly in your predicates.

        Args:
            *predicates: Filter functions that take a Span and return bool

        Returns:
            List of matching spans

        Examples:
            # Single condition
            trace.filter_spans(lambda s: s.name == "controller.reconcile")

            # Multiple conditions (AND)
            trace.filter_spans(
                lambda s: s.name.startswith("reconciler."),
                lambda s: s.duration > 50
            )

            # Complex single predicate
            trace.filter_spans(
                lambda s: s.duration > 50 and "wasm" in s.name
            )

            # Use any Span property
            trace.filter_spans(
                lambda s: s.has_attribute("policy.kind", "AuthPolicy"),
                lambda s: len(s.events) > 0,
                lambda s: s.get_parent_id() is not None
            )
        """
        if not predicates:
            return list(self.spans)

        return [span for span in self.spans if all(pred(span) for pred in predicates)]

    def get_process_services(self) -> set[str]:
        """Get set of service names from all processes"""
        return {process.get("serviceName", "") for process in self.processes.values()}

    def get_span_by_id(self, span_id: str) -> Span | None:
        """Look up a span by its span ID"""
        for span in self.spans:
            if span.span_id == span_id:
                return span
        return None

    def get_children(self, span_id: str) -> list[Span]:
        """Get all direct child spans of the given span"""
        return [span for span in self.spans if span.get_parent_id() == span_id]

    @classmethod
    def from_otlp(cls, resource_spans: list[dict]) -> list["Trace"]:
        """Create list of Traces from OTLP resourceSpans"""
        traces: dict[str, dict] = {}

        for rs in resource_spans:
            resource_attrs = _parse_otlp_attributes(rs.get("resource", {}).get("attributes", []))
            service_name = str(resource_attrs.get("service.name", ""))

            for scope_span in rs.get("scopeSpans", []):
                for span_data in scope_span.get("spans", []):
                    trace_id = span_data.get("traceId", "")
                    if trace_id not in traces:
                        traces[trace_id] = {"spans": [], "processes": {}, "counter": 0}

                    trace = traces[trace_id]

                    process_id = None
                    for pid, proc in trace["processes"].items():
                        if proc["attributes"] == resource_attrs:
                            process_id = pid
                            break
                    if process_id is None:
                        trace["counter"] += 1
                        process_id = f"p{trace['counter']}"
                        trace["processes"][process_id] = {
                            "serviceName": service_name,
                            "attributes": resource_attrs,
                        }

                    trace["spans"].append(Span.from_otlp(span_data, trace_id, process_id))

        return [cls(trace_id=tid, spans=t["spans"], processes=t["processes"]) for tid, t in traces.items()]
