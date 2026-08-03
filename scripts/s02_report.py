#!/usr/bin/env python3
"""Build a bounded S0.2 privileged-companion feasibility report."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.s0_report import metric, percentile
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from s0_report import metric, percentile


SOURCE_COMPONENT = "com.jumpterminator.testsource/.SourceActivity"
TARGET_COMPONENT = "com.jumpterminator.testtarget/.TargetActivity"


def load_events(paths: Iterable[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as error:
                    warnings.append(f"{path}:{line_number}: {error}")
                    continue
                if event.get("schema") != "s0.2-1":
                    warnings.append(f"{path}:{line_number}: unsupported schema")
                    continue
                events.append(event)
    events.sort(key=lambda item: int(item.get("wallClockMs") or 0))
    return events, warnings


def event_key(event: dict[str, Any]) -> tuple[str, int]:
    data = event.get("data") or {}
    return str(event.get("sessionId") or "unknown"), int(data.get("sequence") or 0)


def analyse(events: list[dict[str, Any]]) -> dict[str, Any]:
    ready_events = [event for event in events if event.get("kind") == "ready"]
    block_ready = [
        event
        for event in ready_events
        if (event.get("data") or {}).get("scenario") == "block"
    ]
    allowed_ready = [
        event
        for event in ready_events
        if (event.get("data") or {}).get("scenario") == "allowed-negative"
    ]
    block_session_ids = {str(event.get("sessionId")) for event in block_ready}
    allowed_session_ids = {str(event.get("sessionId")) for event in allowed_ready}
    requested_block = sum(
        int((event.get("data") or {}).get("requestedBlock") or 0)
        for event in block_ready
    )
    requested_allowed = sum(
        int((event.get("data") or {}).get("requestedAllowed") or 0)
        for event in allowed_ready
    )
    executors = sorted(
        {
            str((event.get("data") or {}).get("executor") or "adb_shell_companion")
            for event in ready_events
        },
    )

    all_detections = [event for event in events if event.get("kind") == "target_detected"]
    backs = [event for event in events if event.get("kind") == "back_requested"]
    detections = [
        event for event in all_detections
        if str(event.get("sessionId")) in block_session_ids
    ]
    block_backs = [
        event for event in backs if str(event.get("sessionId")) in block_session_ids
    ]
    dispatched_block_backs = [
        event
        for event in block_backs
        if bool((event.get("data") or {}).get("dispatched"))
    ]
    leaves = [
        event
        for event in events
        if event.get("kind") == "left_target"
        and str(event.get("sessionId")) in block_session_ids
        and bool((event.get("data") or {}).get("leftTarget"))
    ]
    returns = [
        event for event in leaves if bool((event.get("data") or {}).get("returnedSource"))
    ]
    allowed_probes = [
        event
        for event in events
        if event.get("kind") == "allowed_probe"
        and str(event.get("sessionId")) in allowed_session_ids
    ]
    preserved_probes = [
        event for event in allowed_probes if bool((event.get("data") or {}).get("passed"))
    ]
    allowed_backs = [
        event for event in backs if str(event.get("sessionId")) in allowed_session_ids
    ]

    safety_violations: list[str] = []
    detection_counts = Counter(event_key(event) for event in all_detections)
    back_counts = Counter(event_key(event) for event in backs)
    leave_counts = Counter(event_key(event) for event in leaves)
    for key, count in detection_counts.items():
        if count > 1:
            safety_violations.append(f"{key[0]}#{key[1]}: repeated target detection")
    for key, count in back_counts.items():
        if count > 1:
            safety_violations.append(f"{key[0]}#{key[1]}: repeated Back")
    for key, count in leave_counts.items():
        if count > 1:
            safety_violations.append(f"{key[0]}#{key[1]}: repeated final verification")

    detections_by_key = {event_key(event) for event in all_detections}
    for event in backs:
        data = event.get("data") or {}
        key = event_key(event)
        if key not in detections_by_key:
            safety_violations.append(f"{key[0]}#{key[1]}: Back without target detection")
        if data.get("sourceComponent") != SOURCE_COMPONENT:
            safety_violations.append(f"{key[0]}#{key[1]}: unexpected source component")
        if data.get("targetComponent") != TARGET_COMPONENT:
            safety_violations.append(f"{key[0]}#{key[1]}: unexpected target component")
    if allowed_backs:
        safety_violations.append(
            f"armed allowed-negative sessions dispatched {len(allowed_backs)} Back action(s)",
        )

    timeouts = [event for event in events if event.get("kind") == "timeout"]
    failed_events = [
        event
        for event in events
        if event.get("kind") in {"timeout", "service_error", "runner_error"}
    ]
    completed_block_sessions = {
        str(event.get("sessionId"))
        for event in events
        if event.get("kind") == "complete"
        and (event.get("data") or {}).get("reason") == "count_reached"
    }
    expected_block_sessions = {str(event.get("sessionId")) for event in block_ready}
    block_sessions_complete = bool(expected_block_sessions) and (
        expected_block_sessions == completed_block_sessions
    )
    completed_allowed_sessions = {
        str(event.get("sessionId"))
        for event in events
        if event.get("kind") == "complete"
        and (event.get("data") or {}).get("reason") == "stop_requested"
    }
    expected_allowed_sessions = {str(event.get("sessionId")) for event in allowed_ready}
    allowed_sessions_complete = bool(expected_allowed_sessions) and (
        expected_allowed_sessions == completed_allowed_sessions
    )

    detection_latencies = [
        int((event.get("data") or {}).get("detectionUpperBoundMs"))
        for event in detections
        if isinstance((event.get("data") or {}).get("detectionUpperBoundMs"), (int, float))
    ]
    action_latencies = [
        int((event.get("data") or {}).get("requestUpperBoundMs"))
        for event in dispatched_block_backs
        if isinstance((event.get("data") or {}).get("requestUpperBoundMs"), (int, float))
    ]
    leave_latencies = [
        int((event.get("data") or {}).get("leaveUpperBoundMs"))
        for event in leaves
        if isinstance((event.get("data") or {}).get("leaveUpperBoundMs"), (int, float))
    ]
    input_durations = [
        int((event.get("data") or {}).get("inputDurationMs"))
        for event in block_backs
        if isinstance((event.get("data") or {}).get("inputDurationMs"), (int, float))
    ]
    poll_durations = [
        int((event.get("data") or {}).get("pollDurationMs"))
        for event in detections
        if isinstance((event.get("data") or {}).get("pollDurationMs"), (int, float))
    ]

    metrics = {
        "targetDetection": metric(min(len(detections), requested_block), requested_block),
        "backDispatch": metric(
            min(len(dispatched_block_backs), requested_block),
            requested_block,
        ),
        "finalLeaveTarget": metric(min(len(leaves), requested_block), requested_block),
        "returnToSource": metric(min(len(returns), requested_block), requested_block),
        "allowedFlowFalseBlock": metric(
            min(len(allowed_backs), len(allowed_probes)),
            len(allowed_probes),
        ),
        "allowedProbePreserved": metric(len(preserved_probes), len(allowed_probes)),
    }

    def estimate(name: str) -> float | None:
        return metrics[name]["pointEstimate"]

    thresholds_pass = (
        estimate("targetDetection") is not None
        and estimate("targetDetection") >= 0.95
        and estimate("backDispatch") is not None
        and estimate("backDispatch") >= 0.93
        and estimate("finalLeaveTarget") is not None
        and estimate("finalLeaveTarget") >= 0.90
        and estimate("allowedFlowFalseBlock") == 0.0
        and estimate("allowedProbePreserved") == 1.0
        and not safety_violations
        and not failed_events
    )
    sample_gate = (
        requested_block >= 100
        and requested_allowed >= 15
        and len(allowed_probes) >= requested_allowed
        and block_sessions_complete
        and allowed_sessions_complete
    )
    if sample_gate and thresholds_pass:
        decision = (
            "SHIZUKU_POC_FEASIBLE"
            if "shizuku_user_service" in executors
            else "PROCEED_TO_SHIZUKU_POC"
        )
    elif sample_gate:
        decision = "STOP_PRIVILEGED_PATH"
    else:
        decision = "NOT_READY"

    session_summaries: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"scenario": None, "mode": None, "events": 0},
    )
    for event in events:
        session_id = str(event.get("sessionId") or "unknown")
        summary = session_summaries[session_id]
        summary["events"] += 1
        if event.get("kind") == "ready":
            data = event.get("data") or {}
            summary["scenario"] = data.get("scenario")
            summary["mode"] = data.get("mode")

    return {
        "schema": "s0.2-report-1",
        "eventCount": len(events),
        "sessionCount": len(ready_events),
        "executors": executors,
        "sessions": dict(session_summaries),
        "sampleCounts": {
            "requestedBlock": requested_block,
            "requestedAllowed": requested_allowed,
            "targetDetected": len(detections),
            "backDispatched": len(dispatched_block_backs),
            "leftTarget": len(leaves),
            "returnedSource": len(returns),
            "allowedProbes": len(allowed_probes),
            "allowedPreserved": len(preserved_probes),
        },
        "metrics": metrics,
        "latencyUpperBoundMs": {
            "targetDetectionP50": percentile(detection_latencies, 0.50),
            "targetDetectionP95": percentile(detection_latencies, 0.95),
            "backRequestP50": percentile(action_latencies, 0.50),
            "backRequestP95": percentile(action_latencies, 0.95),
            "leaveTargetP50": percentile(leave_latencies, 0.50),
            "leaveTargetP95": percentile(leave_latencies, 0.95),
            "inputDurationP50": percentile(input_durations, 0.50),
            "inputDurationP95": percentile(input_durations, 0.95),
            "pollDurationP50": percentile(poll_durations, 0.50),
            "pollDurationP95": percentile(poll_durations, 0.95),
        },
        "safetyViolations": safety_violations,
        "timeoutCount": len(timeouts),
        "failedEventCount": len(failed_events),
        "blockSessionsComplete": block_sessions_complete,
        "allowedSessionsComplete": allowed_sessions_complete,
        "sampleGatePassed": sample_gate,
        "thresholdGatePassed": thresholds_pass,
        "provisionalDecision": decision,
        "notes": [
            "This is a bounded privileged-companion experiment, not a consumer-app S0 Go.",
            "Latency values are conservative upper bounds from the last observed source sample.",
            (
                "SHIZUKU_POC_FEASIBLE authorizes architecture work, not consumer release."
                if "shizuku_user_service" in executors
                else "PROCEED_TO_SHIZUKU_POC only authorizes a bounded Kotlin UserService prototype."
            ),
        ],
    }


def percentage(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def print_summary(report: dict[str, Any]) -> None:
    print("# Jump Terminator S0.2 privileged companion report")
    print()
    print(f"- Decision: **{report['provisionalDecision']}**")
    print(f"- Sample gate: {report['sampleGatePassed']}")
    print(f"- Threshold gate: {report['thresholdGatePassed']}")
    print()
    print("| Metric | Result | Wilson 95% |")
    print("| --- | ---: | ---: |")
    for name, value in report["metrics"].items():
        low, high = value["wilson95"]
        interval = "n/a" if low is None else f"{percentage(low)} - {percentage(high)}"
        print(
            f"| {name} | {value['successes']}/{value['total']} "
            f"({percentage(value['pointEstimate'])}) | {interval} |",
        )
    print()
    print(
        "Latency upper bounds (ms): "
        + json.dumps(report["latencyUpperBoundMs"], ensure_ascii=False),
    )
    for violation in report["safetyViolations"]:
        print(f"safety: {violation}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("timeline", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    arguments = parser.parse_args()

    events, warnings = load_events(arguments.timeline)
    report = analyse(events)
    report["warnings"] = warnings
    print_summary(report)
    for warning in warnings:
        print(f"warning: {warning}")
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    passing_decisions = {"PROCEED_TO_SHIZUKU_POC", "SHIZUKU_POC_FEASIBLE"}
    if arguments.strict and report["provisionalDecision"] not in passing_decisions:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
