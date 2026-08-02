#!/usr/bin/env python3
"""Generate deterministic S0 metrics and Wilson intervals from exported JSONL."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MATCH_WINDOW_MS = 5_000
EARLY_TOLERANCE_MS = 250
REALTIME_SIGNAL_MAX_AGE_MS = 500
TARGET_ENTRY_MATCH_TOLERANCE_MS = 500
Z_95 = 1.959963984540054


@dataclass
class Sample:
    run_id: str
    sequence: int
    trigger_type: str
    expected: str
    target_package: str
    started_ms: int
    ended_ms: int
    events: list[dict[str, Any]]


def event_time(event: dict[str, Any]) -> int:
    data = event.get("data") or {}
    if event.get("kind") == "ground_truth":
        origin = data.get("originElapsedMs")
        if isinstance(origin, (int, float)) and origin >= 0:
            return int(origin)
    return int(event.get("elapsedRealtimeMs") or 0)


def load_events(paths: Iterable[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    event_ids: set[str] = set()
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as error:
                    warnings.append(f"{path}:{line_number}: invalid JSON ({error.msg})")
                    continue
                event_id = str(event.get("eventId") or "")
                if event_id and event_id in event_ids:
                    continue
                if event_id:
                    event_ids.add(event_id)
                event["_time"] = event_time(event)
                events.append(event)
    events.sort(key=lambda item: (item["_time"], str(item.get("eventId") or "")))
    return events, warnings


def make_samples(events: list[dict[str, Any]]) -> list[Sample]:
    issued = [
        event
        for event in events
        if event.get("kind") == "ground_truth"
        and (event.get("data") or {}).get("phase") == "trigger_issued"
    ]
    issued.sort(key=lambda event: event["_time"])
    samples: list[Sample] = []
    for index, event in enumerate(issued):
        data = event.get("data") or {}
        start = int(event["_time"])
        next_start = int(issued[index + 1]["_time"]) if index + 1 < len(issued) else start + MATCH_WINDOW_MS
        end = min(start + MATCH_WINDOW_MS, next_start)
        window_events = [
            candidate
            for candidate in events
            if start - EARLY_TOLERANCE_MS <= candidate["_time"] < end
        ]
        samples.append(
            Sample(
                run_id=str(data.get("runId") or "unknown"),
                sequence=int(data.get("sequence") or -1),
                trigger_type=str(data.get("triggerType") or "unknown"),
                expected=str(data.get("expected") or "unknown"),
                target_package=str(data.get("targetPackage") or "unknown"),
                started_ms=start,
                ended_ms=end,
                events=window_events,
            )
        )
    return samples


def has_event(sample: Sample, kind: str, predicate=lambda _event: True) -> bool:
    return any(event.get("kind") == kind and predicate(event) for event in sample.events)


def matching_package(sample: Sample, event: dict[str, Any]) -> bool:
    return event.get("packageName") == sample.target_package


def signal_receipt_age_ms(event: dict[str, Any]) -> int | None:
    data = event.get("data") or {}
    kind = event.get("kind")
    value: Any = None
    if kind == "accessibility_signal":
        value = data.get("receiptDelayMs")
    elif kind == "usage_signal":
        receipt_wall = event.get("wallClockMs")
        origin_wall = data.get("eventWallClockMs")
        if isinstance(receipt_wall, (int, float)) and isinstance(origin_wall, (int, float)):
            value = receipt_wall - origin_wall
    elif kind == "transition_candidate":
        value = data.get("signalAgeMs")
    elif kind == "ground_truth":
        origin_elapsed = data.get("originElapsedMs")
        receipt_elapsed = event.get("elapsedRealtimeMs")
        if isinstance(origin_elapsed, (int, float)) and isinstance(receipt_elapsed, (int, float)):
            value = receipt_elapsed - origin_elapsed
    if not isinstance(value, (int, float)) or value < 0:
        return None
    return int(value)


def is_realtime_signal(event: dict[str, Any]) -> bool:
    age = signal_receipt_age_ms(event)
    return age is not None and age <= REALTIME_SIGNAL_MAX_AGE_MS


def metric(successes: int, total: int) -> dict[str, Any]:
    if total == 0:
        return {
            "successes": successes,
            "total": total,
            "pointEstimate": None,
            "wilson95": [None, None],
        }
    point = successes / total
    denominator = 1.0 + Z_95 * Z_95 / total
    center = (point + Z_95 * Z_95 / (2.0 * total)) / denominator
    margin = (
        Z_95
        * math.sqrt(point * (1.0 - point) / total + Z_95 * Z_95 / (4.0 * total * total))
        / denominator
    )
    return {
        "successes": successes,
        "total": total,
        "pointEstimate": point,
        "wilson95": [max(0.0, center - margin), min(1.0, center + margin)],
    }


def percentile(values: list[int], percentile_value: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile_value * len(ordered)) - 1)
    return ordered[index]


def analyse(events: list[dict[str, Any]], samples: list[Sample]) -> dict[str, Any]:
    block_samples = [sample for sample in samples if sample.expected == "block"]
    allow_samples = [sample for sample in samples if sample.expected == "allow"]
    allowed_flow_samples = [sample for sample in allow_samples if sample.trigger_type != "allowed_home"]
    automatic_samples = [sample for sample in block_samples if sample.trigger_type.startswith("automatic")]
    manual_samples = [sample for sample in block_samples if sample.trigger_type == "manual_click"]
    context_samples = [sample for sample in allow_samples if sample.trigger_type == "allowed_home"]

    def access_seen(sample: Sample, realtime: bool) -> bool:
        return has_event(
            sample,
            "accessibility_signal",
            lambda event: matching_package(sample, event)
            and (not realtime or is_realtime_signal(event)),
        )

    def usage_seen(sample: Sample, realtime: bool) -> bool:
        return has_event(
            sample,
            "usage_signal",
            lambda event: matching_package(sample, event)
            and (event.get("data") or {}).get("signal") == "FOREGROUND"
            and (not realtime or is_realtime_signal(event)),
        )

    def candidate_events(sample: Sample, realtime: bool) -> list[dict[str, Any]]:
        return [
            event
            for event in events
            if event.get("kind") == "transition_candidate"
            and matching_candidate(sample, event)
            and (not realtime or is_realtime_signal(event))
        ]

    def candidate_seen(sample: Sample, realtime: bool) -> bool:
        return bool(candidate_events(sample, realtime))

    def target_entered_time(sample: Sample) -> int | None:
        for event in sample.events:
            data = event.get("data") or {}
            if (
                event.get("kind") == "ground_truth"
                and data.get("phase") == "target_entered"
                and str(data.get("runId") or "unknown") == sample.run_id
                and int(data.get("sequence") or -1) == sample.sequence
            ):
                origin = data.get("originElapsedMs")
                return int(origin if isinstance(origin, (int, float)) else event["_time"])
        return None

    def matching_candidate(sample: Sample, event: dict[str, Any]) -> bool:
        if not matching_package(sample, event):
            return False
        data = event.get("data") or {}
        candidate_target_entered = int(data.get("targetEnteredElapsedMs", event["_time"]))
        truth_target_entered = target_entered_time(sample)
        if truth_target_entered is not None:
            return (
                abs(candidate_target_entered - truth_target_entered)
                <= TARGET_ENTRY_MATCH_TOLERANCE_MS
            )
        return (
            sample.started_ms - EARLY_TOLERANCE_MS
            <= candidate_target_entered
            < sample.ended_ms
        )

    def action_seen(sample: Sample) -> bool:
        return has_event(sample, "action_attempt")

    def policy_armed(sample: Sample) -> bool:
        return has_event(
            sample,
            "policy_decision",
            lambda event: bool((event.get("data") or {}).get("shouldAct")),
        )

    def finally_left(sample: Sample) -> bool:
        return has_event(
            sample,
            "action_verification",
            lambda event: bool((event.get("data") or {}).get("leftTarget")),
        )

    acted_samples = [sample for sample in block_samples if policy_armed(sample)]
    combined_acquired = sum(
        access_seen(sample, realtime=True) or usage_seen(sample, realtime=True)
        for sample in block_samples
    )
    accessibility_acquired = sum(access_seen(sample, realtime=True) for sample in block_samples)
    usage_acquired = sum(usage_seen(sample, realtime=True) for sample in block_samples)
    candidates = sum(candidate_seen(sample, realtime=True) for sample in block_samples)
    combined_eventually = sum(
        access_seen(sample, realtime=False) or usage_seen(sample, realtime=False)
        for sample in block_samples
    )
    accessibility_eventually = sum(access_seen(sample, realtime=False) for sample in block_samples)
    usage_eventually = sum(usage_seen(sample, realtime=False) for sample in block_samples)
    candidates_eventually = sum(candidate_seen(sample, realtime=False) for sample in block_samples)
    false_blocks = sum(action_seen(sample) for sample in allow_samples)
    left_target = sum(finally_left(sample) for sample in acted_samples)

    candidate_latencies: list[int] = []
    action_latencies: list[int] = []
    leave_latencies: list[int] = []
    safety_violations: list[str] = []
    for sample in samples:
        matched_candidate_events = candidate_events(sample, realtime=False)
        action_events = [event for event in sample.events if event.get("kind") == "action_attempt"]
        verification_events = [event for event in sample.events if event.get("kind") == "action_verification"]
        latency_origin_ms = target_entered_time(sample) or sample.started_ms
        if matched_candidate_events:
            candidate_latencies.append(
                max(0, int(matched_candidate_events[0]["_time"]) - latency_origin_ms),
            )
        if action_events:
            action_latencies.append(max(0, int(action_events[0]["_time"]) - latency_origin_ms))
        successful_verifications = [
            event for event in verification_events if bool((event.get("data") or {}).get("leftTarget"))
        ]
        if successful_verifications:
            leave_latencies.append(
                max(0, int(successful_verifications[0]["_time"]) - latency_origin_ms),
            )
        stages = [(event.get("data") or {}).get("stage") for event in action_events]
        if stages.count("back") > 1 or stages.count("home") > 1 or len(stages) > 2:
            safety_violations.append(f"{sample.run_id}#{sample.sequence}: repeated global action")

    metrics = {
        "targetEventAcquisitionCombined": metric(combined_acquired, len(block_samples)),
        "targetEventAcquisitionAccessibility": metric(accessibility_acquired, len(block_samples)),
        "targetEventAcquisitionUsageStats": metric(usage_acquired, len(block_samples)),
        "blockCandidateIdentification": metric(candidates, len(block_samples)),
        "targetEventAcquisitionCombinedEventually": metric(combined_eventually, len(block_samples)),
        "targetEventAcquisitionAccessibilityEventually": metric(
            accessibility_eventually,
            len(block_samples),
        ),
        "targetEventAcquisitionUsageStatsEventually": metric(usage_eventually, len(block_samples)),
        "blockCandidateIdentificationEventually": metric(candidates_eventually, len(block_samples)),
        "allowedFlowFalseBlock": metric(false_blocks, len(allow_samples)),
        "finalLeaveTarget": metric(left_target, len(acted_samples)),
    }

    target_packages = {sample.target_package for sample in block_samples}
    accessibility_receipt_ages = [
        age
        for event in events
        if event.get("kind") == "accessibility_signal"
        and event.get("packageName") in target_packages
        and (age := signal_receipt_age_ms(event)) is not None
    ]
    usage_receipt_ages = [
        age
        for event in events
        if event.get("kind") == "usage_signal"
        and event.get("packageName") in target_packages
        and (event.get("data") or {}).get("signal") == "FOREGROUND"
        and (age := signal_receipt_age_ms(event)) is not None
    ]
    candidate_signal_ages = [
        age
        for event in events
        if event.get("kind") == "transition_candidate"
        and event.get("packageName") in target_packages
        and (age := signal_receipt_age_ms(event)) is not None
    ]
    truth_receipt_ages = [
        age
        for event in events
        if event.get("kind") == "ground_truth"
        and (age := signal_receipt_age_ms(event)) is not None
    ]
    sample_gate = (
        len(automatic_samples) >= 100
        and len(manual_samples) >= 100
        and len(allowed_flow_samples) >= 200
        and len(context_samples) >= 50
    )

    def point(name: str) -> float | None:
        return metrics[name]["pointEstimate"]

    threshold_gate = (
        point("targetEventAcquisitionCombined") is not None
        and point("targetEventAcquisitionCombined") >= 0.95
        and point("blockCandidateIdentification") is not None
        and point("blockCandidateIdentification") >= 0.93
        and point("allowedFlowFalseBlock") is not None
        and point("allowedFlowFalseBlock") <= 0.02
        and point("finalLeaveTarget") is not None
        and point("finalLeaveTarget") >= 0.90
        and not safety_violations
    )
    return {
        "reportSchema": "s0-report-2",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "realtimeSignalMaxAgeMs": REALTIME_SIGNAL_MAX_AGE_MS,
        "targetEntryMatchToleranceMs": TARGET_ENTRY_MATCH_TOLERANCE_MS,
        "eventCount": len(events),
        "sampleCounts": {
            "total": len(samples),
            "block": len(block_samples),
            "automaticBlock": len(automatic_samples),
            "manualBlock": len(manual_samples),
            "allowTotal": len(allow_samples),
            "allowedFlow": len(allowed_flow_samples),
            "homeContextBreak": len(context_samples),
            "armedActionEligible": len(acted_samples),
        },
        "metrics": metrics,
        "latencyMs": {
            "candidateP50": percentile(candidate_latencies, 0.50),
            "candidateP95": percentile(candidate_latencies, 0.95),
            "firstActionP50": percentile(action_latencies, 0.50),
            "firstActionP95": percentile(action_latencies, 0.95),
            "leaveTargetP50": percentile(leave_latencies, 0.50),
            "leaveTargetP95": percentile(leave_latencies, 0.95),
            "accessibilityReceiptP50": percentile(accessibility_receipt_ages, 0.50),
            "accessibilityReceiptP95": percentile(accessibility_receipt_ages, 0.95),
            "usageStatsReceiptP50": percentile(usage_receipt_ages, 0.50),
            "usageStatsReceiptP95": percentile(usage_receipt_ages, 0.95),
            "candidateSignalAgeP50": percentile(candidate_signal_ages, 0.50),
            "candidateSignalAgeP95": percentile(candidate_signal_ages, 0.95),
            "groundTruthReceiptP50": percentile(truth_receipt_ages, 0.50),
            "groundTruthReceiptP95": percentile(truth_receipt_ages, 0.95),
        },
        "safetyViolations": safety_violations,
        "sampleGatePassed": sample_gate,
        "thresholdGatePassed": threshold_gate,
        "provisionalDecision": "GO" if sample_gate and threshold_gate else "NOT_READY",
        "notes": [
            "NOT_READY is not automatically a technical No-Go; it also covers incomplete sample counts.",
            "Primary acquisition and candidate metrics require receipt within the realtime age threshold; Eventually metrics only prove delayed delivery.",
            "Lock-screen, recents, multi-window, and device/OEM coverage require the signed manual matrix.",
        ],
    }


def percentage(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def print_summary(report: dict[str, Any]) -> None:
    print("# Jump Terminator S0 report")
    print()
    print(f"- Provisional decision: **{report['provisionalDecision']}**")
    print(f"- Events / samples: {report['eventCount']} / {report['sampleCounts']['total']}")
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
            f"({percentage(value['pointEstimate'])}) | {interval} |"
        )
    print()
    print("Latency (ms): " + json.dumps(report["latencyMs"], ensure_ascii=False))
    if report["safetyViolations"]:
        print("Safety violations:")
        for violation in report["safetyViolations"]:
            print(f"- {violation}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("timeline", nargs="+", type=Path, help="exported S0 JSONL file(s)")
    parser.add_argument("--output", type=Path, help="write machine-readable JSON report")
    parser.add_argument("--strict", action="store_true", help="exit 2 unless the provisional decision is GO")
    arguments = parser.parse_args()

    events, warnings = load_events(arguments.timeline)
    samples = make_samples(events)
    report = analyse(events, samples)
    report["warnings"] = warnings
    print_summary(report)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if arguments.strict and report["provisionalDecision"] != "GO":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
