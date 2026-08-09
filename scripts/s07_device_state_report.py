#!/usr/bin/env python3
"""Aggregate S0.7 recents, split-screen and screen-lock safety evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


EVENT_SCHEMA = "s0.7-1"
REPORT_SCHEMA = "s0.7-device-state-report-1"
SOURCE_COMPONENT = "com.jumpterminator.testsource/.SourceActivity"
TARGET_COMPONENT = "com.jumpterminator.testtarget/.TargetActivity"
SCENARIOS = ("recents", "split-screen", "screen-lock")


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
    events.sort(key=lambda item: int(item.get("wallClockMs") or 0))
    return events, warnings


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _last(events: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    matches = [event for event in events if event.get("kind") == kind]
    return matches[-1] if matches else {}


def _session_evaluation(
    scenario: str,
    cycle: int,
    session_id: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    companion_events = [
        (event.get("data") or {}).get("event")
        for event in events
        if event.get("kind") == "companion_event"
        and isinstance((event.get("data") or {}).get("event"), dict)
    ]
    companion_kinds = [event.get("kind") for event in companion_events]
    foreground_events = [
        event for event in companion_events if event.get("kind") == "foreground_changed"
    ]
    invalidation_reasons = [
        str((event.get("data") or {}).get("reason"))
        for event in companion_events
        if event.get("kind") == "source_context_invalidated"
    ]
    ambiguous_component_sets = [
        set((event.get("data") or {}).get("resumedComponents") or [])
        for event in foreground_events
        if (event.get("data") or {}).get("state") == "ambiguous"
    ]
    boundary = (_last(events, "boundary_injected").get("data") or {})
    target = (_last(events, "target_launched").get("data") or {})
    recovery = (_last(events, "recovery_observed").get("data") or {})
    source_seen = any(
        (event.get("data") or {}).get("state") == "source"
        for event in foreground_events
    )
    target_seen = any(
        (event.get("data") or {}).get("component") == TARGET_COMPONENT
        or TARGET_COMPONENT in ((event.get("data") or {}).get("resumedComponents") or [])
        for event in foreground_events
    )
    common_checks = {
        "scenarioCompleted": bool(_last(events, "scenario_complete")),
        "runnerErrorFree": not any(event.get("kind") == "runner_error" for event in events),
        "readyExactlyOnce": companion_kinds.count("ready") == 1,
        "sourceWasObserved": source_seen and bool(_last(events, "source_observed")),
        "targetLaunchSucceeded": target.get("exitCode") == 0,
        "targetWasObserved": target_seen,
        "noTargetDetection": companion_kinds.count("target_detected") == 0,
        "noBackRequested": companion_kinds.count("back_requested") == 0,
        "noServiceError": companion_kinds.count("service_error") == 0,
    }
    scenario_checks: dict[str, bool]
    if scenario == "recents":
        resumed = set(boundary.get("topResumedComponents") or [])
        scenario_checks = {
            "sourceContextInvalidatedByRecents": "foreground_changed"
            in invalidation_reasons,
            "recentsRemovedSourceFromTop": SOURCE_COMPONENT not in resumed,
        }
    elif scenario == "split-screen":
        resumed = set(target.get("topResumedComponents") or [])
        scenario_checks = {
            "bothTestActivitiesResumed": {SOURCE_COMPONENT, TARGET_COMPONENT}
            <= resumed,
            "splitScreenStateObserved": int(target.get("splitScreenMarkerCount") or 0)
            > 0,
            "ambiguousForegroundObserved": any(
                {SOURCE_COMPONENT, TARGET_COMPONENT} <= components
                for components in ambiguous_component_sets
            ),
            "sourceContextInvalidatedByAmbiguity": "foreground_ambiguous"
            in invalidation_reasons,
        }
    elif scenario == "screen-lock":
        scenario_checks = {
            "nonInteractiveBoundaryObserved": boundary.get("interactive") is False,
            "sourceContextInvalidatedWhileAsleep": "device_not_interactive"
            in invalidation_reasons,
            "deviceRecoveredInteractive": recovery.get("interactive") is True,
            "deviceRecoveredUnlocked": recovery.get("keyguardLocked") is False,
        }
    else:
        scenario_checks = {"knownScenario": False}
    checks = {**common_checks, **scenario_checks}
    return {
        "scenario": scenario,
        "cycle": cycle,
        "sessionId": session_id,
        "gatePassed": all(checks.values()),
        "checks": checks,
        "observed": {
            "companionEventCount": len(companion_events),
            "invalidationReasons": invalidation_reasons,
            "boundary": boundary,
            "target": target,
            "recovery": recovery or None,
        },
    }


def analyse(
    events: list[dict[str, Any]],
    positive_report: dict[str, Any],
    *,
    expected_recents: int,
    expected_split_screen: int,
    expected_screen_lock: int,
) -> dict[str, Any]:
    expected_counts = {
        "recents": expected_recents,
        "split-screen": expected_split_screen,
        "screen-lock": expected_screen_lock,
    }
    grouped: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    malformed_events = 0
    for event in events:
        scenario = event.get("scenario")
        cycle = event.get("cycle")
        session_id = event.get("sessionId")
        if (
            scenario not in SCENARIOS
            or not isinstance(cycle, int)
            or isinstance(cycle, bool)
            or cycle <= 0
            or not isinstance(session_id, str)
            or len(session_id) != 32
        ):
            malformed_events += 1
            continue
        grouped[(scenario, cycle, session_id)].append(event)

    sessions = [
        _session_evaluation(scenario, cycle, session_id, session_events)
        for (scenario, cycle, session_id), session_events in sorted(grouped.items())
    ]
    scenario_summaries: dict[str, Any] = {}
    coverage_passed = malformed_events == 0
    session_ids = [session["sessionId"] for session in sessions]
    session_ids_unique = len(session_ids) == len(set(session_ids))
    for scenario, expected in expected_counts.items():
        scenario_sessions = [
            session for session in sessions if session["scenario"] == scenario
        ]
        cycles = {session["cycle"] for session in scenario_sessions}
        expected_cycles = set(range(1, expected + 1))
        scenario_coverage = (
            len(scenario_sessions) == expected and cycles == expected_cycles
        )
        coverage_passed = coverage_passed and scenario_coverage
        scenario_summaries[scenario] = {
            "expectedCycles": expected,
            "observedCycles": len(scenario_sessions),
            "coveragePassed": scenario_coverage,
            "gatePassed": scenario_coverage
            and all(session["gatePassed"] for session in scenario_sessions),
            "sessions": scenario_sessions,
        }

    counts = positive_report.get("sampleCounts") or {}
    authorization = positive_report.get("authorization") or {}
    positive_checks = {
        "reportSchemaIsS02": positive_report.get("schema") == "s0.2-report-1",
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
        "capabilityAndRuleBound": authorization.get("allSessionsOneTimeCapability") is True
        and authorization.get("allSessionsRuleSnapshotBound") is True,
        "noSafetyViolations": not positive_report.get("safetyViolations"),
        "noTimeouts": positive_report.get("timeoutCount") == 0,
        "noFailedEvents": positive_report.get("failedEventCount") == 0,
        "reportHasNoWarnings": not positive_report.get("warnings"),
    }
    positive_gate = all(positive_checks.values())
    sample_gate = (
        coverage_passed
        and session_ids_unique
        and counts.get("requestedBlock") == 10
    )
    negative_gate = all(
        summary["gatePassed"] for summary in scenario_summaries.values()
    )
    safety_gate = sample_gate and negative_gate and positive_gate
    violations: list[str] = []
    if malformed_events:
        violations.append(f"{malformed_events} malformed S0.7 evidence events")
    if not session_ids_unique:
        violations.append("S0.7 session IDs are reused")
    for session in sessions:
        if not session["gatePassed"]:
            failed = [name for name, passed in session["checks"].items() if not passed]
            violations.append(
                f"{session['scenario']} cycle {session['cycle']}: " + ", ".join(failed)
            )
    if not positive_gate:
        failed = [name for name, passed in positive_checks.items() if not passed]
        violations.append("fullscreen positive control: " + ", ".join(failed))
    if not sample_gate:
        decision = "NOT_READY"
    elif safety_gate:
        decision = "S07_DEVICE_STATE_GATE_PASSED"
    else:
        decision = "STOP_S07_DEVICE_STATE_PATH"
    return {
        "schema": REPORT_SCHEMA,
        "expected": expected_counts,
        "deviceStateStress": scenario_summaries,
        "sessionIdsUnique": session_ids_unique,
        "fullscreenPositiveControl": {
            "checks": positive_checks,
            "gatePassed": positive_gate,
            "sampleCounts": counts,
            "latencyUpperBoundMs": positive_report.get("latencyUpperBoundMs"),
        },
        "sampleGatePassed": sample_gate,
        "safetyGatePassed": safety_gate,
        "safetyViolations": violations,
        "provisionalDecision": decision,
        "notes": [
            "Recents, split-screen and screen-lock samples are zero-action contexts.",
            "The fullscreen positive control preserves the fixed-package Back behavior.",
            "This gate covers one MIUI 14 device and debug automation only.",
        ],
    }


def apply_warnings(report: dict[str, Any], warnings: list[str]) -> None:
    report["warnings"] = warnings
    if not warnings:
        return
    report["safetyViolations"].extend(
        f"evidence warning: {warning}" for warning in warnings
    )
    report["safetyGatePassed"] = False
    report["provisionalDecision"] = (
        "STOP_S07_DEVICE_STATE_PATH" if report["sampleGatePassed"] else "NOT_READY"
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
    print("# Jump Terminator S0.7 device-state report")
    print()
    print(f"- Decision: **{report['provisionalDecision']}**")
    print(f"- Sample gate: {report['sampleGatePassed']}")
    print(f"- Safety gate: {report['safetyGatePassed']}")
    for scenario in SCENARIOS:
        value = report["deviceStateStress"][scenario]
        print(
            f"- {scenario}: {value['observedCycles']}/{value['expectedCycles']} "
            f"(gate={value['gatePassed']})"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--positive-timeline", type=Path, required=True)
    parser.add_argument("--positive-report", type=Path, required=True)
    parser.add_argument("--expected-recents", type=int, required=True)
    parser.add_argument("--expected-split-screen", type=int, required=True)
    parser.add_argument("--expected-screen-lock", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    arguments = parser.parse_args()

    events, warnings = load_events(arguments.timeline)
    report = analyse(
        events,
        load_json(arguments.positive_report),
        expected_recents=arguments.expected_recents,
        expected_split_screen=arguments.expected_split_screen,
        expected_screen_lock=arguments.expected_screen_lock,
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
    if arguments.strict and report["provisionalDecision"] != "S07_DEVICE_STATE_GATE_PASSED":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
