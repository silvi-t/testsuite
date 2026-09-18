"""
WASM configuration tracing tests.
"""

import hashlib

import pytest

pytestmark = [pytest.mark.observability, pytest.mark.limitador, pytest.mark.authorino, pytest.mark.kuadrant_only]


@pytest.fixture(scope="module")
def wasm_config_span(tracing, authorization, rate_limit, skip_or_fail):
    """Find BuildConfigForPath span containing both auth and rate limit policies"""
    traces = tracing.get_traces(service="kuadrant-operator")

    # Find BuildConfigForPath span that has both policies and matches our topology
    for trace in traces:
        spans = trace.filter_spans(
            lambda s: s.name == "wasm.BuildConfigForPath",
            lambda s: f"authpolicy.kuadrant.io:kuadrant/{authorization.name()}"
            in str(s.get_attribute("source_policies")),
            lambda s: f"ratelimitpolicy.kuadrant.io:kuadrant/{rate_limit.name()}"
            in str(s.get_attribute("source_policies")),
        )
        if spans:
            return {"trace": trace, "span": spans[0]}

    skip_or_fail("No BuildConfigForPath span found with both policies for topology")
    return None


@pytest.fixture(scope="module")
def wasm_merge_span(wasm_config_span, skip_or_fail):
    """MergeAndVerifySpecs child span of BuildConfigForPath"""
    trace = wasm_config_span["trace"]
    parent_span = wasm_config_span["span"]

    children = trace.get_children(parent_span.span_id)
    merge_span = next((s for s in children if s.name == "wasm.MergeAndVerifySpecs"), None)

    if merge_span is None:
        skip_or_fail("No wasm.MergeAndVerifySpecs child span found")

    return merge_span


@pytest.fixture(scope="module")
def wasm_actionset_span(wasm_config_span, skip_or_fail):
    """ActionSet.create child span of BuildConfigForPath"""
    trace = wasm_config_span["trace"]
    parent_span = wasm_config_span["span"]

    children = trace.get_children(parent_span.span_id)
    actionset_span = next((s for s in children if s.name == "wasm.ActionSet.create"), None)

    if actionset_span is None:
        skip_or_fail("No wasm.ActionSet.create child span found")

    return actionset_span


@pytest.fixture(scope="module")
def wasm_action_builder_span(wasm_config_span, skip_or_fail):
    """BuildActionSetsForPath child span of BuildConfigForPath"""
    trace = wasm_config_span["trace"]
    parent_span = wasm_config_span["span"]

    children = trace.get_children(parent_span.span_id)
    builder_span = next((s for s in children if s.name == "wasm.BuildActionSetsForPath"), None)

    if builder_span is None:
        skip_or_fail("No wasm.BuildActionSetsForPath child span found")

    return builder_span


def test_wasm_config_matches_topology(wasm_config_span, cluster, gateway, route):
    """Validate BuildConfigForPath span matches the test topology"""
    span = wasm_config_span["span"]

    assert span.get_attribute("gateway.name") == gateway.name()
    assert span.get_attribute("gateway.namespace") == cluster.project
    assert span.get_attribute("route.name") == route.name()
    assert span.get_attribute("route.namespace") == cluster.project
    assert span.get_attribute("route_type") == "HTTP"
    assert span.get_attribute("listener.name") == "api"
    assert span.has_attribute("path_id")


def test_wasm_config_action_validation_metrics(wasm_config_span):
    """Validate BuildConfigForPath has action validation metrics"""
    span = wasm_config_span["span"]

    assert span.has_attribute("specs.before_merge")
    assert span.has_attribute("specs.validated")
    assert span.has_attribute("specs.invalid")
    assert span.has_attribute("specs.after_merge")

    validated = span.get_attribute("specs.validated")
    assert validated > 0, "Should have validated at least one action"

    invalid = span.get_attribute("specs.invalid")
    assert invalid == 0, f"Should have no invalid actions, got {invalid}"


def test_wasm_merge_action_consistency(wasm_config_span, wasm_merge_span):
    """Validate MergeAndVerifySpecs is correlated and has consistent spec counts"""
    config_span = wasm_config_span["span"]

    # Verify merge span has expected metrics
    assert wasm_merge_span.has_attribute("specs.input")
    assert wasm_merge_span.has_attribute("specs.merged")
    assert wasm_merge_span.has_attribute("specs.output")

    # Data consistency: merge input should match config validated actions
    merge_input = wasm_merge_span.get_attribute("specs.input")
    config_validated = config_span.get_attribute("specs.validated")
    assert (
        merge_input == config_validated
    ), f"Merge input ({merge_input}) should match config validated ({config_validated})"

    # Output should not exceed input
    merge_output = wasm_merge_span.get_attribute("specs.output")
    assert merge_output <= merge_input, f"Merge output ({merge_output}) should not exceed input ({merge_input})"


def test_wasm_actionset_correlation(wasm_config_span, wasm_actionset_span):
    """Validate ActionSet.create spans have both auth and rate limit actions with correct hash"""
    config_span = wasm_config_span["span"]

    assert wasm_actionset_span.has_attribute("actionset.name")
    assert wasm_actionset_span.has_attribute("hostname")
    assert wasm_actionset_span.has_attribute("match_index")

    # Compute expected actionset name hash
    hostname = wasm_actionset_span.get_attribute("hostname")
    match_index = wasm_actionset_span.get_attribute("match_index")
    source = f'{config_span.get_attribute("path_id")}|{match_index + 1}|{hostname}'
    expected_name = hashlib.sha256(source.encode()).hexdigest()

    actual_name = wasm_actionset_span.get_attribute("actionset.name")
    assert actual_name == expected_name, f"ActionSet name mismatch: expected {expected_name}, got {actual_name}"


def test_wasm_action_builder_correlation(wasm_action_builder_span):
    """Validate BuildActionSetsForPath shows grpc action types"""
    action_types = str(wasm_action_builder_span.get_attribute("action_types"))
    assert "grpc" in action_types
