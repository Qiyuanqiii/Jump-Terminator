#!/usr/bin/env python3
"""Aggregate S0.8 picture-in-picture fail-closed evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


EVENT_SCHEMA = "s0.8-1"
PIP_EVENT_SCHEMA = "s0.8-pip-1"
SNAPSHOT_SCHEMA = "s0.8-activity-snapshot-1"
REPORT_SCHEMA = "s0.8-pip-context-report-1"
PASS_DECISION = "S08_PIP_CONTEXT_GATE_PASSED"
STOP_DECISION = "STOP_S08_PIP_CONTEXT_PATH"
SOURCE_COMPONENT = "com.jumpterminator.testsource/.SourceActivity"
SOURCE_PACKAGE = "com.jumpterminator.testsource"
TARGET_COMPONENT = "com.jumpterminator.testtarget/.TargetActivity"
TARGET_PACKAGE = "com.jumpterminator.testtarget"
CONTROL_PACKAGE = "com.jumpterminator.s02"
SCENARIOS = ("target-preexisting-pip", "source-pip-target")
SESSION_ID_PATTERN = re.compile(r"[a-f0-9]{32}")
SHA256_PATTERN = re.compile(r"[A-F0-9]{64}")
LOWER_SHA256_PATTERN = re.compile(r"[a-f0-9]{64}")
CAPABILITY_FINGERPRINT_PATTERN = re.compile(r"[a-f0-9]{16}")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _has_dual_clock(value: dict[str, Any]) -> bool:
    return (
        _is_int(value.get("wallClockMs"))
        and int(value["wallClockMs"]) > 0
        and _is_int(value.get("elapsedRealtimeMs"))
        and int(value["elapsedRealtimeMs"]) >= 0
    )


def _ready_authorization_checks(
    ready_events: list[dict[str, Any]],
    *,
    expected_block_count: int,
) -> dict[str, bool]:
    event = ready_events[0] if len(ready_events) == 1 else {}
    data = event.get("data") or {}
    signing_hashes = data.get("ownerSigningCertificateSha256")
    signing_identity_valid = (
        isinstance(signing_hashes, list)
        and bool(signing_hashes)
        and all(
            isinstance(value, str)
            and LOWER_SHA256_PATTERN.fullmatch(value) is not None
            for value in signing_hashes
        )
    )
    event_elapsed = event.get("elapsedRealtimeMs")
    lease_duration = data.get("leaseDurationMs")
    lease_deadline = data.get("leaseDeadlineElapsedMs")
    return {
        "exactlyOnce": len(ready_events) == 1,
        "dualClock": len(ready_events) == 1 and _has_dual_clock(event),
        "armedBlockConfiguration": data.get("scenario") == "block"
        and data.get("mode") == "armed"
        and data.get("requestedBlock") == expected_block_count
        and data.get("requestedAllowed") == 0,
        "fixedTransitionBound": data.get("sourceComponent") == SOURCE_COMPONENT
        and data.get("targetComponent") == TARGET_COMPONENT,
        "shizukuExecutor": data.get("executor") == "shizuku_user_service",
        "ownerIdentityBound": data.get("ownerBound") is True
        and data.get("ownerUidSource") == "binder"
        and _is_int(data.get("ownerUid"))
        and int(data["ownerUid"]) > 0
        and _is_int(data.get("ownerUserId"))
        and int(data["ownerUserId"]) >= 0
        and data.get("ownerPackage") == CONTROL_PACKAGE
        and signing_identity_valid,
        "capabilityRuleAndLeaseBound": data.get("authorizationProtocol") == "s0.4-1"
        and data.get("oneTimeCapability") is True
        and isinstance(data.get("capabilityFingerprint"), str)
        and CAPABILITY_FINGERPRINT_PATTERN.fullmatch(
            str(data["capabilityFingerprint"])
        )
        is not None
        and isinstance(data.get("ruleSnapshotSha256"), str)
        and LOWER_SHA256_PATTERN.fullmatch(str(data["ruleSnapshotSha256"]))
        is not None
        and _is_int(lease_duration)
        and int(lease_duration) > 0
        and _is_int(event_elapsed)
        and _is_int(lease_deadline)
        and int(lease_deadline) > int(event_elapsed)
        and int(lease_deadline) - int(event_elapsed) <= int(lease_duration)
        and data.get("finalActionSerialization") == "authorization_lock",
    }


def load_events(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        return [], [f"{path}: unable to read: {error}"]
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            warnings.append(f"{path}:{line_number}: invalid JSON: {error.msg}")
            continue
        if not isinstance(event, dict) or event.get("schema") != EVENT_SCHEMA:
            warnings.append(f"{path}:{line_number}: unsupported schema")
            continue
        events.append(event)
    events.sort(
        key=lambda item: (
            int(item.get("elapsedRealtimeMs") or 0),
            int(item.get("wallClockMs") or 0),
        )
    )
    return events, warnings


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def load_positive_timeline(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        return [], [f"{path}: unable to read: {error}"]
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            warnings.append(f"{path}:{line_number}: invalid JSON: {error.msg}")
            continue
        if (
            not isinstance(event, dict)
            or event.get("schema") != "s0.2-1"
            or not isinstance(event.get("sessionId"), str)
            or SESSION_ID_PATTERN.fullmatch(str(event["sessionId"])) is None
            or not _is_int(event.get("wallClockMs"))
            or int(event["wallClockMs"]) <= 0
        ):
            warnings.append(f"{path}:{line_number}: invalid S0.2 positive event")
            continue
        events.append(event)
    return events, warnings


def _events_of_kind(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [event for event in events if event.get("kind") == kind]


def _last(events: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    matches = _events_of_kind(events, kind)
    return matches[-1] if matches else {}


def _embedded_events(
    events: list[dict[str, Any]],
    wrapper_kind: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for wrapper in events:
        if wrapper.get("kind") != wrapper_kind:
            continue
        event = (wrapper.get("data") or {}).get("event")
        if isinstance(event, dict):
            result.append(event)
    return result


def _raw_embedding_valid(
    wrapper: dict[str, Any],
    *,
    expected_schema: str,
    expected_session_id: str,
    expected_role: str | None = None,
) -> bool:
    data = wrapper.get("data") or {}
    raw = data.get("raw")
    event = data.get("event")
    if not isinstance(raw, str) or not isinstance(event, dict):
        return False
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return (
        decoded == event
        and event.get("schema") == expected_schema
        and event.get("sessionId") == expected_session_id
        and isinstance(event.get("kind"), str)
        and bool(event.get("kind"))
        and _has_dual_clock(event)
        and (expected_role is None or event.get("role") == expected_role)
    )


def _event_value(event: dict[str, Any], name: str) -> Any:
    if name in event:
        return event[name]
    data = event.get("data")
    if isinstance(data, dict):
        return data.get(name)
    return None


def _top_components(snapshot: dict[str, Any]) -> list[str]:
    components: list[str] = []
    for item in snapshot.get("topResumed") or []:
        if isinstance(item, dict) and isinstance(item.get("component"), str):
            components.append(str(item["component"]))
    return components


def _snapshot_structure_checks(snapshot: Any) -> dict[str, bool]:
    if not isinstance(snapshot, dict):
        return {
            "snapshotSchema": False,
            "snapshotDualClock": False,
            "snapshotDigest": False,
            "structuredDisplays": False,
            "structuredTopResumed": False,
            "structuredWindowingTasks": False,
            "structuredPinnedTasks": False,
        }

    displays = snapshot.get("displays")
    top_resumed = snapshot.get("topResumed")
    windowing_tasks = snapshot.get("windowingTasks")
    pinned_tasks = snapshot.get("pinnedTasks")
    display_ids = {
        item.get("displayId")
        for item in displays or []
        if isinstance(item, dict) and _is_int(item.get("displayId"))
    }
    displays_valid = isinstance(displays, list) and bool(displays) and all(
        isinstance(item, dict)
        and _is_int(item.get("displayId"))
        and isinstance(item.get("topResumedComponents"), list)
        and all(isinstance(value, str) for value in item["topResumedComponents"])
        and isinstance(item.get("tasks"), list)
        for item in displays
    )
    top_valid = isinstance(top_resumed, list) and bool(top_resumed) and all(
        isinstance(item, dict)
        and _is_int(item.get("displayId"))
        and item.get("displayId") in display_ids
        and isinstance(item.get("component"), str)
        and bool(item.get("component"))
        for item in top_resumed
    )

    def task_valid(item: Any) -> bool:
        return (
            isinstance(item, dict)
            and _is_int(item.get("displayId"))
            and item.get("displayId") in display_ids
            and _is_int(item.get("taskId"))
            and (
                item.get("packageName") is None
                or isinstance(item.get("packageName"), str)
            )
            and isinstance(item.get("windowingMode"), str)
            and bool(item.get("windowingMode"))
            and isinstance(item.get("activityComponents"), list)
            and all(
                isinstance(component, str)
                for component in item.get("activityComponents") or []
            )
        )

    windowing_valid = (
        isinstance(windowing_tasks, list)
        and bool(windowing_tasks)
        and all(task_valid(item) for item in windowing_tasks)
    )
    pinned_valid = isinstance(pinned_tasks, list) and all(
        task_valid(item) and item.get("windowingMode") == "pinned"
        for item in pinned_tasks
    )
    return {
        "snapshotSchema": snapshot.get("schema") == SNAPSHOT_SCHEMA,
        "snapshotDualClock": _has_dual_clock(
            {
                "wallClockMs": snapshot.get("capturedWallClockMs"),
                "elapsedRealtimeMs": snapshot.get("capturedElapsedRealtimeMs"),
            }
        ),
        "snapshotDigest": isinstance(snapshot.get("rawActivitySha256"), str)
        and SHA256_PATTERN.fullmatch(str(snapshot["rawActivitySha256"])) is not None,
        "structuredDisplays": displays_valid,
        "structuredTopResumed": top_valid,
        "structuredWindowingTasks": windowing_valid,
        "structuredPinnedTasks": pinned_valid,
    }


def _boundary_checks(
    boundary: dict[str, Any],
    expected_package: str,
    expected_operation: str,
    expected_top_component: str,
) -> tuple[dict[str, bool], dict[str, Any]]:
    data = boundary.get("data") or {}
    snapshot = data.get("snapshot")
    structure = _snapshot_structure_checks(snapshot)
    pinned_tasks = snapshot.get("pinnedTasks") if isinstance(snapshot, dict) else []
    windowing_tasks = (
        snapshot.get("windowingTasks") if isinstance(snapshot, dict) else []
    )
    pinned_match = any(
        isinstance(task, dict)
        and task.get("packageName") == expected_package
        and task.get("windowingMode") == "pinned"
        for task in pinned_tasks or []
    )
    windowing_match = any(
        isinstance(task, dict)
        and task.get("packageName") == expected_package
        and task.get("windowingMode") == "pinned"
        for task in windowing_tasks or []
    )
    active = (
        isinstance(snapshot, dict)
        and snapshot.get("pictureInPictureActive") is True
    )
    checks = {
        **structure,
        "boundaryOperationBound": data.get("operation") == expected_operation,
        "expectedPinnedPackageBound": data.get("expectedPinnedPackage")
        == expected_package,
        "expectedTopResumed": expected_top_component in _top_components(snapshot)
        if isinstance(snapshot, dict)
        else False,
        "pictureInPictureActive": active,
        "expectedPackagePinned": pinned_match,
        "windowingModePinned": windowing_match,
    }
    return checks, snapshot if isinstance(snapshot, dict) else {}


def _topology_event_checks(
    event: dict[str, Any],
    *,
    expected_top_component: str,
    expected_pinned_package: str | None,
) -> tuple[dict[str, bool], dict[str, Any]]:
    data = event.get("data") or {}
    snapshot = data.get("snapshot")
    structure = _snapshot_structure_checks(snapshot)
    pinned_tasks = snapshot.get("pinnedTasks") if isinstance(snapshot, dict) else []
    expected_pinned = expected_pinned_package is not None
    pinned_match = any(
        isinstance(task, dict)
        and task.get("packageName") == expected_pinned_package
        and task.get("windowingMode") == "pinned"
        for task in pinned_tasks or []
    )
    active = (
        isinstance(snapshot, dict)
        and snapshot.get("pictureInPictureActive") is True
    )
    checks = {
        **structure,
        "expectedTopResumed": expected_top_component in _top_components(snapshot)
        if isinstance(snapshot, dict)
        else False,
        "expectedPinnedState": pinned_match if expected_pinned else not pinned_tasks,
        "pictureInPictureState": active if expected_pinned else not active,
    }
    return checks, snapshot if isinstance(snapshot, dict) else {}


def _target_presented_checks(
    event: dict[str, Any],
    scenario: str,
) -> dict[str, bool]:
    data = event.get("data") or {}
    snapshot = data.get("snapshot")
    structure = _snapshot_structure_checks(snapshot)
    top = _top_components(snapshot) if isinstance(snapshot, dict) else []
    pinned = snapshot.get("pinnedTasks") if isinstance(snapshot, dict) else []
    source_still_pinned = any(
        isinstance(task, dict)
        and task.get("packageName") == SOURCE_PACKAGE
        and task.get("windowingMode") == "pinned"
        for task in pinned or []
    )
    target_still_pinned = any(
        isinstance(task, dict)
        and task.get("packageName") == TARGET_PACKAGE
        and task.get("windowingMode") == "pinned"
        for task in pinned or []
    )
    return {
        "targetCommandSucceeded": data.get("exitCode") == 0,
        "targetTopResumed": TARGET_COMPONENT in top,
        "targetSnapshotStructured": all(structure.values()),
        "expectedPostLaunchPipTopology": (
            not target_still_pinned
            if scenario == "target-preexisting-pip"
            else source_still_pinned
        ),
    }


def _session_evaluation(
    scenario: str,
    cycle: int,
    session_id: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    events = sorted(
        events,
        key=lambda item: (
            int(item.get("elapsedRealtimeMs") or 0),
            int(item.get("wallClockMs") or 0),
        ),
    )
    companion_wrappers = _events_of_kind(events, "companion_event")
    pip_wrappers = _events_of_kind(events, "pip_event")
    companion_events = _embedded_events(events, "companion_event")
    pip_events = _embedded_events(events, "pip_event")
    companion_kinds = [event.get("kind") for event in companion_events]
    foreground_events = [
        event for event in companion_events if event.get("kind") == "foreground_changed"
    ]
    expected_package = (
        TARGET_PACKAGE if scenario == "target-preexisting-pip" else SOURCE_PACKAGE
    )
    expected_role = "target" if scenario == "target-preexisting-pip" else "source"
    expected_operation = (
        "expand_pinned_target"
        if scenario == "target-preexisting-pip"
        else "source_pip_reveals_target"
    )
    expected_boundary_top = (
        SOURCE_COMPONENT
        if scenario == "target-preexisting-pip"
        else TARGET_COMPONENT
    )
    boundary_events = _events_of_kind(events, "pip_boundary_observed")
    boundary = boundary_events[-1] if boundary_events else {}
    boundary_checks, boundary_snapshot = _boundary_checks(
        boundary,
        expected_package,
        expected_operation,
        expected_boundary_top,
    )
    target_events = _events_of_kind(events, "target_presented")
    target_event = target_events[-1] if target_events else {}
    target_checks = _target_presented_checks(target_event, scenario)
    target_snapshot = (target_event.get("data") or {}).get("snapshot")

    requested_events = [
        event
        for event in pip_events
        if event.get("schema") == PIP_EVENT_SCHEMA
        and event.get("sessionId") == session_id
        and event.get("role") == expected_role
        and event.get("kind") == "pip_requested"
        and _event_value(event, "accepted") is True
        and _has_dual_clock(event)
    ]
    active_events = [
        event
        for event in pip_events
        if event.get("schema") == PIP_EVENT_SCHEMA
        and event.get("sessionId") == session_id
        and event.get("role") == expected_role
        and event.get("kind") == "pip_mode_changed"
        and _event_value(event, "active") is True
        and _has_dual_clock(event)
    ]
    boundary_elapsed = (
        boundary_snapshot.get("capturedElapsedRealtimeMs")
        if isinstance(boundary_snapshot, dict)
        else None
    )
    pip_precedes_boundary = (
        bool(requested_events)
        and bool(active_events)
        and _is_int(boundary_elapsed)
        and max(
            int(requested_events[0]["elapsedRealtimeMs"]),
            int(active_events[0]["elapsedRealtimeMs"]),
        )
        <= int(boundary_elapsed)
    )
    target_elapsed = (
        target_snapshot.get("capturedElapsedRealtimeMs")
        if isinstance(target_snapshot, dict)
        else None
    )
    target_at_or_after_boundary = (
        _is_int(boundary_elapsed)
        and _is_int(target_elapsed)
        and int(boundary_elapsed) <= int(target_elapsed)
    )
    pip_foreground_observed = any(
        (event.get("data") or {}).get("state") == "picture_in_picture"
        and (event.get("data") or {}).get("pictureInPictureActive") is True
        and expected_package in ((event.get("data") or {}).get("pinnedPackages") or [])
        and (event.get("data") or {}).get("component") == expected_boundary_top
        and expected_boundary_top
        in ((event.get("data") or {}).get("resumedComponents") or [])
        for event in foreground_events
    )
    target_foreground_observed = any(
        (event.get("data") or {}).get("component") == TARGET_COMPONENT
        or TARGET_COMPONENT in ((event.get("data") or {}).get("resumedComponents") or [])
        for event in foreground_events
    )
    ready_events = [event for event in companion_events if event.get("kind") == "ready"]
    ready_checks = _ready_authorization_checks(
        ready_events,
        expected_block_count=1,
    )
    monitor_complete_events = [
        event for event in companion_events if event.get("kind") == "complete"
    ]
    invalidation_events = [
        event
        for event in companion_events
        if event.get("kind") == "source_context_invalidated"
        and (event.get("data") or {}).get("reason") == "picture_in_picture"
    ]
    invalidation_topology_events = [
        event
        for event in invalidation_events
        if (event.get("data") or {}).get("pictureInPictureActive") is True
        and SOURCE_PACKAGE
        in ((event.get("data") or {}).get("pinnedPackages") or [])
    ]
    invalidation_reasons = [
        str((event.get("data") or {}).get("reason"))
        for event in companion_events
        if event.get("kind") == "source_context_invalidated"
    ]
    source_state_events = [
        event
        for event in foreground_events
        if (event.get("data") or {}).get("state") == "source"
        and (event.get("data") or {}).get("component") == SOURCE_COMPONENT
        and (event.get("data") or {}).get("pictureInPictureActive") is False
    ]
    any_source_context_events = [
        event
        for event in foreground_events
        if (event.get("data") or {}).get("state") == "source"
    ]
    companion_embeddings_valid = bool(companion_wrappers) and all(
        _raw_embedding_valid(
            item,
            expected_schema="s0.2-1",
            expected_session_id=session_id,
        )
        for item in companion_wrappers
    )
    pip_embeddings_valid = len(pip_wrappers) >= 2 and all(
        _raw_embedding_valid(
            item,
            expected_schema=PIP_EVENT_SCHEMA,
            expected_session_id=session_id,
            expected_role=expected_role,
        )
        for item in pip_wrappers
    )
    wrapper_clocks_valid = bool(events) and all(_has_dual_clock(event) for event in events)
    target_detection_count = companion_kinds.count("target_detected")
    back_requested_count = companion_kinds.count("back_requested")
    back_dispatched_count = sum(
        (event.get("data") or {}).get("dispatched") is True
        for event in companion_events
        if event.get("kind") == "back_requested"
    )
    scenario_complete_events = _events_of_kind(events, "scenario_complete")
    scenario_complete = scenario_complete_events[-1] if scenario_complete_events else {}
    scenario_complete_data = scenario_complete.get("data") or {}
    monitor_stop_events = _events_of_kind(events, "monitor_stop_requested")

    ready_elapsed = (
        ready_events[0].get("elapsedRealtimeMs") if len(ready_events) == 1 else None
    )
    monitor_complete_elapsed = (
        monitor_complete_events[0].get("elapsedRealtimeMs")
        if len(monitor_complete_events) == 1
        else None
    )
    monitor_stop_elapsed = (
        monitor_stop_events[0].get("elapsedRealtimeMs")
        if len(monitor_stop_events) == 1
        else None
    )
    ready_data = ready_events[0].get("data") or {} if len(ready_events) == 1 else {}
    authorization_lease_deadline = ready_data.get("leaseDeadlineElapsedMs")
    scenario_complete_elapsed = scenario_complete.get("elapsedRealtimeMs")
    monitor_complete_data = (
        monitor_complete_events[0].get("data") or {}
        if len(monitor_complete_events) == 1
        else {}
    )
    completion_counts_valid = (
        len(monitor_complete_events) == 1
        and _is_int(monitor_complete_data.get("detections"))
        and _is_int(monitor_complete_data.get("actions"))
    )
    completion_counts_match = (
        completion_counts_valid
        and monitor_complete_data.get("detections") == target_detection_count
        and monitor_complete_data.get("actions") == back_dispatched_count
    )
    completion_counts_zero = (
        completion_counts_valid
        and monitor_complete_data.get("detections") == 0
        and monitor_complete_data.get("actions") == 0
    )
    completion_reports_nonzero = completion_counts_valid and (
        monitor_complete_data.get("detections") != 0
        or monitor_complete_data.get("actions") != 0
    )
    authorization_lease_covers_observation = (
        _is_int(authorization_lease_deadline)
        and all(
            _is_int(value)
            and int(value) <= int(authorization_lease_deadline)
            for value in (
                boundary_elapsed,
                target_elapsed,
                monitor_stop_elapsed,
                monitor_complete_elapsed,
            )
        )
    )
    monitor_closed_before_summary = (
        _is_int(monitor_stop_elapsed)
        and _is_int(monitor_complete_elapsed)
        and _is_int(scenario_complete_elapsed)
        and int(monitor_stop_elapsed)
        <= int(monitor_complete_elapsed)
        <= int(scenario_complete_elapsed)
    )
    summary_counts_match = (
        scenario_complete_data.get("targetDetections") == target_detection_count
        and scenario_complete_data.get("backRequests") == back_requested_count
        and scenario_complete_data.get("monitorCompletionObserved") is True
        and scenario_complete_data.get("result")
        == (
            "zero_action_observed"
            if target_detection_count == 0 and back_requested_count == 0
            else "unsafe_action_observed"
        )
    )

    common_readiness = {
        "scenarioStartedExactlyOnce": len(_events_of_kind(events, "scenario_started"))
        == 1,
        "scenarioCompletedExactlyOnce": len(scenario_complete_events) == 1,
        "runnerErrorFree": not _events_of_kind(events, "runner_error"),
        "wrapperDualClocksValid": wrapper_clocks_valid,
        **{f"ready.{name}": passed for name, passed in ready_checks.items()},
        "monitorStopRequestedExactlyOnce": len(monitor_stop_events) == 1,
        "monitorCompletedExactlyOnce": len(monitor_complete_events) == 1,
        "monitorCompletedByStop": len(monitor_complete_events) == 1
        and (monitor_complete_events[0].get("data") or {}).get("reason")
        == "stop_requested",
        "monitorCompletionCountsMatchEmbeddedEvents": completion_counts_match,
        "monitorCompletedWithZeroActionCounts": completion_counts_zero,
        "authorizationLeaseCoversPipObservation": authorization_lease_covers_observation,
        "monitorClosedBeforeScenarioSummary": monitor_closed_before_summary,
        "scenarioSummaryMatchesEmbeddedEvents": summary_counts_match,
        "noCompanionTimeout": companion_kinds.count("timeout") == 0,
        "noServiceError": companion_kinds.count("service_error") == 0,
        "embeddedCompanionIdentityAndRawValid": companion_embeddings_valid,
        "embeddedPipIdentityAndRawValid": pip_embeddings_valid,
        "pipRequestAcceptedExactlyOnce": len(requested_events) == 1,
        "pipModeActiveEventObservedExactlyOnce": len(active_events) == 1,
        "pipEventsPrecedeBoundary": pip_precedes_boundary,
        "pipForegroundStateObserved": pip_foreground_observed,
        "oneStructuredPipBoundary": len(boundary_events) == 1,
        "oneTargetPresentation": len(target_events) == 1,
        "targetPresentedAtOrAfterBoundary": target_at_or_after_boundary,
        "targetForegroundObserved": target_foreground_observed,
        **{f"boundary.{name}": passed for name, passed in boundary_checks.items()},
        **{f"target.{name}": passed for name, passed in target_checks.items()},
    }
    if scenario == "target-preexisting-pip":
        pip_entered_events = _events_of_kind(events, "pip_entered")
        pip_entered = pip_entered_events[-1] if pip_entered_events else {}
        pip_entered_checks, pip_entered_snapshot = _topology_event_checks(
            pip_entered,
            expected_top_component=SOURCE_COMPONENT,
            expected_pinned_package=TARGET_PACKAGE,
        )
        source_presented_events = _events_of_kind(events, "source_presented_with_pip")
        source_presented = source_presented_events[-1] if source_presented_events else {}
        source_presented_checks, source_presented_snapshot = _topology_event_checks(
            source_presented,
            expected_top_component=SOURCE_COMPONENT,
            expected_pinned_package=TARGET_PACKAGE,
        )
        active_elapsed = active_events[0].get("elapsedRealtimeMs") if active_events else None
        pip_entered_elapsed = pip_entered_snapshot.get("capturedElapsedRealtimeMs")
        source_presented_elapsed = source_presented_snapshot.get(
            "capturedElapsedRealtimeMs"
        )
        target_preexisting_order = (
            _is_int(active_elapsed)
            and _is_int(pip_entered_elapsed)
            and _is_int(ready_elapsed)
            and _is_int(source_presented_elapsed)
            and _is_int(boundary_elapsed)
            and int(active_elapsed)
            <= int(pip_entered_elapsed)
            <= int(ready_elapsed)
            <= int(source_presented_elapsed)
            <= int(boundary_elapsed)
        )
        scenario_readiness = {
            "pipEnteredEvidenceExactlyOnce": len(pip_entered_events) == 1,
            "sourcePresentedWhileTargetPinnedExactlyOnce": len(source_presented_events)
            == 1,
            "sourceContextNeverEstablishedWhilePip": len(any_source_context_events)
            == 0,
            "preexistingPipCausalOrder": target_preexisting_order,
            **{
                f"pipEntered.{name}": passed
                for name, passed in pip_entered_checks.items()
            },
            **{
                f"sourcePresented.{name}": passed
                for name, passed in source_presented_checks.items()
            },
        }
    else:
        target_underlay_events = _events_of_kind(events, "target_underlay_ready")
        target_underlay = target_underlay_events[-1] if target_underlay_events else {}
        target_underlay_checks, target_underlay_snapshot = _topology_event_checks(
            target_underlay,
            expected_top_component=TARGET_COMPONENT,
            expected_pinned_package=None,
        )
        source_observed_events = _events_of_kind(events, "source_observed")
        source_observed = source_observed_events[-1] if source_observed_events else {}
        source_observed_checks, source_observed_snapshot = _topology_event_checks(
            source_observed,
            expected_top_component=SOURCE_COMPONENT,
            expected_pinned_package=None,
        )
        underlay_elapsed = target_underlay_snapshot.get("capturedElapsedRealtimeMs")
        source_state_elapsed = (
            source_state_events[0].get("elapsedRealtimeMs")
            if source_state_events
            else None
        )
        source_observed_elapsed = source_observed_snapshot.get(
            "capturedElapsedRealtimeMs"
        )
        active_elapsed = active_events[0].get("elapsedRealtimeMs") if active_events else None
        invalidation_elapsed = (
            invalidation_events[0].get("elapsedRealtimeMs")
            if invalidation_events
            else None
        )
        source_pip_order = (
            _is_int(ready_elapsed)
            and _is_int(underlay_elapsed)
            and _is_int(source_state_elapsed)
            and _is_int(source_observed_elapsed)
            and _is_int(active_elapsed)
            and _is_int(invalidation_elapsed)
            and _is_int(boundary_elapsed)
            and int(ready_elapsed)
            <= int(underlay_elapsed)
            <= int(source_state_elapsed)
            <= int(source_observed_elapsed)
            and int(source_state_elapsed) < int(active_elapsed) <= int(boundary_elapsed)
            and int(source_state_elapsed)
            < int(invalidation_elapsed)
            <= int(boundary_elapsed)
        )
        scenario_readiness = {
            "targetUnderlayEvidenceExactlyOnce": len(target_underlay_events) == 1,
            "sourceContextEvidenceExactlyOnce": len(source_state_events) == 1
            and len(source_observed_events) == 1,
            "sourceContextInvalidatedByPipExactlyOnce": len(invalidation_events) == 1,
            "sourceInvalidationCarriesPipTopology": len(invalidation_events) == 1
            and len(invalidation_topology_events) == 1,
            "sourcePipCausalOrder": source_pip_order,
            **{
                f"targetUnderlay.{name}": passed
                for name, passed in target_underlay_checks.items()
            },
            **{
                f"sourceObserved.{name}": passed
                for name, passed in source_observed_checks.items()
            },
        }
    readiness_checks = {**common_readiness, **scenario_readiness}
    safety_checks = {
        "noTargetDetectionInPipContext": target_detection_count == 0,
        "noBackRequestedInPipContext": back_requested_count == 0,
        "monitorCompletionReportsNoPipActions": not completion_reports_nonzero,
    }
    hard_stop = not all(safety_checks.values())
    readiness_passed = all(readiness_checks.values())
    return {
        "scenario": scenario,
        "cycle": cycle,
        "sessionId": session_id,
        "readinessPassed": readiness_passed,
        "hardStopObserved": hard_stop,
        "gatePassed": readiness_passed and not hard_stop,
        "readinessChecks": readiness_checks,
        "safetyChecks": safety_checks,
        "observed": {
            "companionEventCount": len(companion_events),
            "pipEventCount": len(pip_events),
            "targetDetectionCount": target_detection_count,
            "backRequestedCount": back_requested_count,
            "backDispatchedCount": back_dispatched_count,
            "monitorCompletionDetections": monitor_complete_data.get("detections"),
            "monitorCompletionActions": monitor_complete_data.get("actions"),
            "invalidationReasons": invalidation_reasons,
            "monitorCompletionReason": (
                (monitor_complete_events[0].get("data") or {}).get("reason")
                if len(monitor_complete_events) == 1
                else None
            ),
            "boundary": (boundary.get("data") or {}) if boundary else None,
            "target": (target_event.get("data") or {}) if target_event else None,
        },
    }


def _positive_control(
    positive_report: dict[str, Any],
    positive_events: list[dict[str, Any]],
) -> dict[str, Any]:
    counts = positive_report.get("sampleCounts") or {}
    authorization = positive_report.get("authorization") or {}
    report_sessions = positive_report.get("sessions") or {}
    timeline_session_ids = {
        str(event.get("sessionId")) for event in positive_events
    }
    kinds = [event.get("kind") for event in positive_events]
    ready_events = [event for event in positive_events if event.get("kind") == "ready"]
    detected_events = [
        event for event in positive_events if event.get("kind") == "target_detected"
    ]
    back_events = [
        event for event in positive_events if event.get("kind") == "back_requested"
    ]
    left_events = [
        event for event in positive_events if event.get("kind") == "left_target"
    ]
    complete_events = [
        event for event in positive_events if event.get("kind") == "complete"
    ]
    complete_data = (
        complete_events[0].get("data") or {} if len(complete_events) == 1 else {}
    )
    positive_ready_checks = _ready_authorization_checks(
        ready_events,
        expected_block_count=10,
    )
    ready_event = ready_events[0] if len(ready_events) == 1 else {}
    ready_data = ready_event.get("data") or {}
    complete_event = complete_events[0] if len(complete_events) == 1 else {}
    expected_sequences = set(range(1, 11))

    def sequence_map(values: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        return {
            int((event.get("data") or {})["sequence"]): event
            for event in values
            if _is_int((event.get("data") or {}).get("sequence"))
        }

    detected_by_sequence = sequence_map(detected_events)
    back_by_sequence = sequence_map(back_events)
    left_by_sequence = sequence_map(left_events)
    sequences_exact = all(
        len(values) == 10 and set(sequence_map(values)) == expected_sequences
        for values in (detected_events, back_events, left_events)
    )
    sequences_paired = sequences_exact and all(
        _has_dual_clock(detected_by_sequence[sequence])
        and _has_dual_clock(back_by_sequence[sequence])
        and _has_dual_clock(left_by_sequence[sequence])
        and int(detected_by_sequence[sequence]["elapsedRealtimeMs"])
        <= int(back_by_sequence[sequence]["elapsedRealtimeMs"])
        <= int(left_by_sequence[sequence]["elapsedRealtimeMs"])
        and int(detected_by_sequence[sequence]["wallClockMs"])
        <= int(back_by_sequence[sequence]["wallClockMs"])
        <= int(left_by_sequence[sequence]["wallClockMs"])
        and (back_by_sequence[sequence].get("data") or {}).get("dispatched") is True
        and (left_by_sequence[sequence].get("data") or {}).get("leftTarget") is True
        and (left_by_sequence[sequence].get("data") or {}).get("returnedSource")
        is True
        for sequence in expected_sequences
    ) and all(
        int(left_by_sequence[sequence]["elapsedRealtimeMs"])
        < int(detected_by_sequence[sequence + 1]["elapsedRealtimeMs"])
        and int(left_by_sequence[sequence]["wallClockMs"])
        < int(detected_by_sequence[sequence + 1]["wallClockMs"])
        for sequence in range(1, 10)
    )
    ready_actions_complete_chain = (
        sequences_paired
        and _has_dual_clock(ready_event)
        and _has_dual_clock(complete_event)
        and int(ready_event["elapsedRealtimeMs"])
        <= int(detected_by_sequence[1]["elapsedRealtimeMs"])
        and int(ready_event["wallClockMs"])
        <= int(detected_by_sequence[1]["wallClockMs"])
        and int(left_by_sequence[10]["elapsedRealtimeMs"])
        <= int(complete_event["elapsedRealtimeMs"])
        and int(left_by_sequence[10]["wallClockMs"])
        <= int(complete_event["wallClockMs"])
    )
    lease_deadline = ready_data.get("leaseDeadlineElapsedMs")
    actions_within_ready_lease = (
        sequences_paired
        and _is_int(lease_deadline)
        and all(
            int(event["elapsedRealtimeMs"]) <= int(lease_deadline)
            for event in detected_events + back_events + left_events
        )
    )
    timeline_counts = {
        "targetDetected": len(detected_events),
        "backDispatched": sum(
            (event.get("data") or {}).get("dispatched") is True
            for event in back_events
        ),
        "leftTarget": sum(
            (event.get("data") or {}).get("leftTarget") is True
            for event in left_events
        ),
        "returnedSource": sum(
            (event.get("data") or {}).get("returnedSource") is True
            for event in left_events
        ),
    }
    checks = {
        "reportSchemaIsS02": positive_report.get("schema") == "s0.2-report-1",
        "timelinePresent": bool(positive_events),
        "timelineHasOneSession": len(timeline_session_ids) == 1,
        "timelineSessionMatchesReport": len(timeline_session_ids) == 1
        and isinstance(report_sessions, dict)
        and set(report_sessions) == timeline_session_ids,
        "timelineEventCountMatchesReport": positive_report.get("eventCount")
        == len(positive_events),
        **{
            f"timelineReady.{name}": passed
            for name, passed in positive_ready_checks.items()
        },
        "timelineDetectedTen": len(detected_events) == 10,
        "timelineBackDispatchedTen": len(back_events) == 10
        and timeline_counts["backDispatched"] == 10,
        "timelineLeftAndReturnedTen": len(left_events) == 10
        and timeline_counts["leftTarget"] == 10
        and timeline_counts["returnedSource"] == 10,
        "timelineSequencesExactlyOneToTen": sequences_exact,
        "timelineSequencesCausallyPaired": sequences_paired,
        "timelineReadyActionsCompleteCausalChain": ready_actions_complete_chain,
        "timelineActionsWithinReadyLease": actions_within_ready_lease,
        "timelineCompletedTen": len(complete_events) == 1
        and complete_data.get("reason") == "count_reached"
        and complete_data.get("detections") == 10
        and complete_data.get("actions") == 10,
        "timelineHasNoFailureEvents": kinds.count("timeout") == 0
        and kinds.count("service_error") == 0
        and kinds.count("runner_error") == 0,
        "reportCountsMatchTimeline": all(
            counts.get(name) == value for name, value in timeline_counts.items()
        ),
        "usesShizukuUserService": positive_report.get("executors")
        == ["shizuku_user_service"],
        "requestedTen": counts.get("requestedBlock") == 10,
        "detectedTen": counts.get("targetDetected") == 10,
        "backDispatchedTen": counts.get("backDispatched") == 10,
        "leftTargetTen": counts.get("leftTarget") == 10,
        "returnedSourceTen": counts.get("returnedSource") == 10,
        "sessionCompleted": positive_report.get("blockSessionsComplete") is True,
        "ownerIdentityBound": authorization.get("allSessionsBinderDerived") is True
        and authorization.get("allSessionsSigningIdentityResolved") is True,
        "capabilityAndRuleBound": authorization.get("allSessionsOneTimeCapability")
        is True
        and authorization.get("allSessionsRuleSnapshotBound") is True,
        "noSafetyViolations": not positive_report.get("safetyViolations"),
        "noTimeouts": positive_report.get("timeoutCount") == 0,
        "noFailedEvents": positive_report.get("failedEventCount") == 0,
        "reportHasNoWarnings": not positive_report.get("warnings"),
    }
    return {
        "checks": checks,
        "gatePassed": all(checks.values()),
        "sampleCounts": counts,
        "timelineCounts": timeline_counts,
        "latencyUpperBoundMs": positive_report.get("latencyUpperBoundMs"),
    }


def analyse(
    events: list[dict[str, Any]],
    positive_report: dict[str, Any],
    positive_events: list[dict[str, Any]],
    *,
    expected_target_preexisting_pip: int,
    expected_source_pip_target: int,
) -> dict[str, Any]:
    for name, value in (
        ("expected_target_preexisting_pip", expected_target_preexisting_pip),
        ("expected_source_pip_target", expected_source_pip_target),
    ):
        if not _is_int(value) or value < 1:
            raise ValueError(f"{name} must be an integer greater than or equal to 1")
    expected_counts = {
        "target-preexisting-pip": expected_target_preexisting_pip,
        "source-pip-target": expected_source_pip_target,
    }
    grouped: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    malformed_events = 0
    for event in events:
        scenario = event.get("scenario")
        cycle = event.get("cycle")
        session_id = event.get("sessionId")
        if (
            scenario not in SCENARIOS
            or not _is_int(cycle)
            or int(cycle) <= 0
            or not isinstance(session_id, str)
            or SESSION_ID_PATTERN.fullmatch(session_id) is None
        ):
            malformed_events += 1
            continue
        grouped[(str(scenario), int(cycle), session_id)].append(event)

    sessions = [
        _session_evaluation(scenario, cycle, session_id, session_events)
        for (scenario, cycle, session_id), session_events in sorted(grouped.items())
    ]
    scenario_summaries: dict[str, Any] = {}
    coverage_gate = malformed_events == 0
    session_ids = [session["sessionId"] for session in sessions]
    session_ids_unique = len(session_ids) == len(set(session_ids))
    for scenario, expected in expected_counts.items():
        selected = [session for session in sessions if session["scenario"] == scenario]
        cycles = {session["cycle"] for session in selected}
        expected_cycles = set(range(1, expected + 1))
        coverage = len(selected) == expected and cycles == expected_cycles
        coverage_gate = coverage_gate and coverage
        scenario_summaries[scenario] = {
            "expectedCycles": expected,
            "observedCycles": len(selected),
            "coveragePassed": coverage,
            "readinessPassed": coverage
            and all(session["readinessPassed"] for session in selected),
            "hardStopObserved": any(session["hardStopObserved"] for session in selected),
            "gatePassed": coverage
            and all(session["gatePassed"] for session in selected),
            "sessions": selected,
        }

    positive = _positive_control(positive_report, positive_events)
    all_sessions_ready = bool(sessions) and all(
        session["readinessPassed"] for session in sessions
    )
    hard_stop = any(session["hardStopObserved"] for session in sessions)
    readiness_gate = (
        coverage_gate
        and session_ids_unique
        and all_sessions_ready
        and positive["gatePassed"]
    )
    safety_gate = readiness_gate and not hard_stop
    readiness_gaps: list[str] = []
    safety_violations: list[str] = []
    if malformed_events:
        readiness_gaps.append(f"{malformed_events} malformed S0.8 evidence events")
    if not session_ids_unique:
        readiness_gaps.append("S0.8 session IDs are reused")
    for scenario, summary in scenario_summaries.items():
        if not summary["coveragePassed"]:
            readiness_gaps.append(
                f"{scenario}: observed {summary['observedCycles']} of "
                f"{summary['expectedCycles']} required cycles"
            )
    for session in sessions:
        if not session["readinessPassed"]:
            failed = [
                name
                for name, passed in session["readinessChecks"].items()
                if not passed
            ]
            readiness_gaps.append(
                f"{session['scenario']} cycle {session['cycle']}: " + ", ".join(failed)
            )
        if session["hardStopObserved"]:
            failed = [
                name for name, passed in session["safetyChecks"].items() if not passed
            ]
            safety_violations.append(
                f"{session['scenario']} cycle {session['cycle']}: " + ", ".join(failed)
            )
    if not positive["gatePassed"]:
        failed = [name for name, passed in positive["checks"].items() if not passed]
        readiness_gaps.append("fullscreen positive control: " + ", ".join(failed))

    if hard_stop:
        decision = STOP_DECISION
    elif safety_gate:
        decision = PASS_DECISION
    else:
        decision = "NOT_READY"
    return {
        "schema": REPORT_SCHEMA,
        "expected": expected_counts,
        "pipNegativeStress": scenario_summaries,
        "sessionIdsUnique": session_ids_unique,
        "coverageGatePassed": coverage_gate,
        "fullscreenPositiveControl": positive,
        "sampleGatePassed": readiness_gate,
        "hardStopObserved": hard_stop,
        "safetyGatePassed": safety_gate,
        "readinessGaps": readiness_gaps,
        "safetyViolations": safety_violations,
        "provisionalDecision": decision,
        "notes": [
            "Both PiP scenarios are zero-action contexts and require a system-confirmed pinned task.",
            "Any target detection or Back request in a PiP session is a hard stop.",
            "Missing topology evidence, runner errors, timeouts and an incomplete 10/10 fullscreen control are NOT_READY.",
            "This gate covers fixed test packages on one MIUI 14 device only.",
        ],
    }


def apply_warnings(report: dict[str, Any], warnings: list[str]) -> None:
    report["warnings"] = warnings
    if not warnings:
        return
    report["readinessGaps"].extend(
        f"evidence warning: {warning}" for warning in warnings
    )
    report["sampleGatePassed"] = False
    report["safetyGatePassed"] = False
    report["provisionalDecision"] = (
        STOP_DECISION if report.get("hardStopObserved") else "NOT_READY"
    )


def source_evidence(paths: Iterable[Path]) -> list[dict[str, str]]:
    return [
        {
            "file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        }
        for path in paths
    ]


def print_summary(report: dict[str, Any]) -> None:
    print("# Jump Terminator S0.8 PiP context report")
    print()
    print(f"- Decision: **{report['provisionalDecision']}**")
    print(f"- Sample gate: {report['sampleGatePassed']}")
    print(f"- Safety gate: {report['safetyGatePassed']}")
    for scenario in SCENARIOS:
        value = report["pipNegativeStress"][scenario]
        print(
            f"- {scenario}: {value['observedCycles']}/{value['expectedCycles']} "
            f"(gate={value['gatePassed']})"
        )
    counts = report["fullscreenPositiveControl"]["sampleCounts"]
    print(
        "- fullscreen-positive: "
        f"{counts.get('backDispatched', 0)}/10 "
        f"(gate={report['fullscreenPositiveControl']['gatePassed']})"
    )


def _positive_cycle_count(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected cycle count must be an integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("expected cycle count must be at least 1")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--positive-timeline", type=Path, required=True)
    parser.add_argument("--positive-report", type=Path, required=True)
    parser.add_argument(
        "--expected-target-preexisting-pip",
        type=_positive_cycle_count,
        required=True,
    )
    parser.add_argument(
        "--expected-source-pip-target",
        type=_positive_cycle_count,
        required=True,
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    arguments = parser.parse_args()

    events, warnings = load_events(arguments.timeline)
    positive_events, positive_warnings = load_positive_timeline(
        arguments.positive_timeline
    )
    warnings.extend(positive_warnings)
    report = analyse(
        events,
        load_json(arguments.positive_report),
        positive_events,
        expected_target_preexisting_pip=arguments.expected_target_preexisting_pip,
        expected_source_pip_target=arguments.expected_source_pip_target,
    )
    report["sourceEvidence"] = source_evidence(
        [arguments.timeline, arguments.positive_timeline, arguments.positive_report]
    )
    apply_warnings(report, warnings)
    print_summary(report)
    for warning in warnings:
        print(f"warning: {warning}")
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if arguments.strict and report["provisionalDecision"] != PASS_DECISION:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
