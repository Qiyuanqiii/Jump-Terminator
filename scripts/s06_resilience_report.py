#!/usr/bin/env python3
"""Aggregate S0.6 crash, repeated-target and reauthorization stress evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.s03_lifecycle_report import analyse as analyse_lifecycle
    from scripts.s03_lifecycle_report import load_events as load_lifecycle_events
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from s03_lifecycle_report import analyse as analyse_lifecycle
    from s03_lifecycle_report import load_events as load_lifecycle_events


REPORT_SCHEMA = "s0.6-resilience-report-1"
REAUTH_SCHEMA = "s0.6-reauth-1"
SESSION_ID_PATTERN = re.compile(r"[a-f0-9]{32}")
REAUTH_EVENT_SEQUENCE = (
    "permission_revoked",
    "revoked_probe",
    "permission_restored",
    "recovered_probe",
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def load_reauthorization_events(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
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
        if not isinstance(event, dict) or event.get("schema") != REAUTH_SCHEMA:
            warnings.append(f"{path}:{line_number}: unsupported schema")
            continue
        events.append(event)
    return events, warnings


def _reauthorization_summary(
    events: list[dict[str, Any]],
    expected_cycles: int,
) -> tuple[dict[str, Any], list[str]]:
    by_cycle: dict[int, list[dict[str, Any]]] = defaultdict(list)
    violations: list[str] = []
    for event in events:
        cycle = event.get("cycle")
        if not isinstance(cycle, int) or isinstance(cycle, bool) or cycle <= 0:
            violations.append("reauthorization event has an invalid cycle")
            continue
        by_cycle[cycle].append(event)

    expected = set(range(1, expected_cycles + 1))
    observed = set(by_cycle)
    evaluations: list[dict[str, Any]] = []
    all_probe_session_ids: list[str] = []
    for cycle in sorted(observed):
        cycle_events = by_cycle[cycle]
        event_sequence = tuple(str(event.get("kind")) for event in cycle_events)
        by_kind = {
            str(event.get("kind")): event
            for event in cycle_events
            if event.get("kind") is not None
        }
        revoked = by_kind.get("permission_revoked") or {}
        denied_probe = by_kind.get("revoked_probe") or {}
        restored = by_kind.get("permission_restored") or {}
        recovered_probe = by_kind.get("recovered_probe") or {}
        revoked_session_id = denied_probe.get("sessionId")
        recovered_session_id = recovered_probe.get("sessionId")
        probe_session_ids = [revoked_session_id, recovered_session_id]
        valid_distinct_sessions = (
            all(
                isinstance(session_id, str)
                and SESSION_ID_PATTERN.fullmatch(session_id) is not None
                for session_id in probe_session_ids
            )
            and revoked_session_id != recovered_session_id
        )
        if valid_distinct_sessions:
            all_probe_session_ids.extend(probe_session_ids)
        checks = {
            "eventSequenceIsExact": event_sequence == REAUTH_EVENT_SEQUENCE,
            "permissionWasRevoked": revoked.get("granted") is False,
            "revokedProbeHadNoReady": denied_probe.get("readyCount") == 0,
            "permissionWasRestored": restored.get("granted") is True,
            "recoveredProbeHadOneReady": recovered_probe.get("readyCount") == 1,
            "probeSessionIdsAreDistinctAndValid": valid_distinct_sessions,
        }
        if not checks["eventSequenceIsExact"]:
            violations.append(f"reauthorization cycle {cycle}: event sequence is ambiguous")
        if not checks["revokedProbeHadNoReady"]:
            violations.append(f"reauthorization cycle {cycle}: privileged ready while revoked")
        if not checks["recoveredProbeHadOneReady"]:
            violations.append(f"reauthorization cycle {cycle}: did not recover exactly once")
        if not checks["probeSessionIdsAreDistinctAndValid"]:
            violations.append(f"reauthorization cycle {cycle}: invalid probe session identity")
        evaluations.append(
            {
                "cycle": cycle,
                "gatePassed": all(checks.values()),
                "checks": checks,
                "revokedSessionId": revoked_session_id,
                "recoveredSessionId": recovered_session_id,
            }
        )

    coverage = observed == expected
    session_ids_unique = (
        len(all_probe_session_ids) == expected_cycles * 2
        and len(set(all_probe_session_ids)) == len(all_probe_session_ids)
    )
    if coverage and not session_ids_unique:
        violations.append("reauthorization probe session IDs are reused across cycles")
    gate = (
        coverage
        and session_ids_unique
        and len(evaluations) == expected_cycles
        and all(item["gatePassed"] for item in evaluations)
    )
    return (
        {
            "expectedCycles": expected_cycles,
            "observedCycles": len(observed),
            "missingCycles": sorted(expected - observed),
            "unexpectedCycles": sorted(observed - expected),
            "coveragePassed": coverage,
            "allProbeSessionIdsUnique": session_ids_unique,
            "gatePassed": gate,
            "cycles": evaluations,
        },
        violations,
    )


def analyse(
    lifecycle_events: list[dict[str, Any]],
    block_report: dict[str, Any],
    reauthorization_events: list[dict[str, Any]],
    *,
    expected_crash_cycles: int,
    expected_targets: int,
    expected_reauthorization_cycles: int,
) -> dict[str, Any]:
    lifecycle = analyse_lifecycle(lifecycle_events)
    crash_sessions = [
        session
        for session in lifecycle.get("sessions", [])
        if session.get("scenario") == "ui-kill"
    ]
    crash_checks = {
        "cycleCountReached": len(crash_sessions) == expected_crash_cycles,
        "allObservationsValid": len(crash_sessions) == expected_crash_cycles
        and all(session.get("observationValid") is True for session in crash_sessions),
        "allLifecycleChecksPassed": len(crash_sessions) == expected_crash_cycles
        and all(session.get("gatePassed") is True for session in crash_sessions),
        "allOwnersDetached": len(crash_sessions) == expected_crash_cycles
        and all(
            ((session.get("observed") or {}).get("companionResult") or {}).get(
                "ownerDetachments",
                0,
            )
            >= 1
            for session in crash_sessions
        ),
        "allServicesExited": len(crash_sessions) == expected_crash_cycles
        and all(
            ((session.get("observed") or {}).get("companionResult") or {}).get(
                "serviceExitRequests",
                0,
            )
            >= 1
            for session in crash_sessions
        ),
    }
    crash_gate = all(crash_checks.values())

    counts = block_report.get("sampleCounts") or {}
    authorization = block_report.get("authorization") or {}
    repeated_target_checks = {
        "reportSchemaIsS02": block_report.get("schema") == "s0.2-report-1",
        "usesShizukuUserService": block_report.get("executors") == [
            "shizuku_user_service"
        ],
        "reportHasNoWarnings": not block_report.get("warnings"),
        "requestedCountMatched": counts.get("requestedBlock") == expected_targets,
        "allTargetsDetected": counts.get("targetDetected") == expected_targets,
        "allBacksDispatched": counts.get("backDispatched") == expected_targets,
        "allTargetsLeft": counts.get("leftTarget") == expected_targets,
        "allSourcesReturned": counts.get("returnedSource") == expected_targets,
        "sessionCompleted": block_report.get("blockSessionsComplete") is True,
        "noSafetyViolations": not block_report.get("safetyViolations"),
        "noTimeouts": block_report.get("timeoutCount") == 0,
        "noFailedEvents": block_report.get("failedEventCount") == 0,
        "ownerIdentityBound": authorization.get("allSessionsBinderDerived") is True
        and authorization.get("allSessionsSigningIdentityResolved") is True,
        "capabilityAndRuleBound": authorization.get("allSessionsOneTimeCapability") is True
        and authorization.get("allSessionsRuleSnapshotBound") is True,
    }
    repeated_target_gate = all(repeated_target_checks.values())

    reauthorization, reauthorization_violations = _reauthorization_summary(
        reauthorization_events,
        expected_reauthorization_cycles,
    )
    sample_gate = (
        len(crash_sessions) == expected_crash_cycles
        and counts.get("requestedBlock") == expected_targets
        and reauthorization.get("observedCycles") == expected_reauthorization_cycles
    )
    violations = list(lifecycle.get("safetyViolations") or [])
    violations.extend(reauthorization_violations)
    safety_gate = (
        sample_gate
        and crash_gate
        and repeated_target_gate
        and reauthorization.get("gatePassed") is True
        and not violations
    )
    if not sample_gate:
        decision = "NOT_READY"
    elif safety_gate:
        decision = "S06_RESILIENCE_STRESS_PASSED"
    else:
        decision = "STOP_S06_RESILIENCE_PATH"

    return {
        "schema": REPORT_SCHEMA,
        "expected": {
            "crashCycles": expected_crash_cycles,
            "repeatedTargets": expected_targets,
            "reauthorizationCycles": expected_reauthorization_cycles,
        },
        "crashStress": {
            "observedCycles": len(crash_sessions),
            "checks": crash_checks,
            "gatePassed": crash_gate,
            "sessions": crash_sessions,
        },
        "repeatedTargetStress": {
            "checks": repeated_target_checks,
            "gatePassed": repeated_target_gate,
            "sampleCounts": counts,
            "latencyUpperBoundMs": block_report.get("latencyUpperBoundMs"),
        },
        "reauthorizationStress": reauthorization,
        "sampleGatePassed": sample_gate,
        "safetyGatePassed": safety_gate,
        "safetyViolations": violations,
        "provisionalDecision": decision,
        "notes": [
            "The crash grace covers only the already bounded one-action session.",
            "Revoked Shizuku permission must produce no privileged ready event.",
            "This stress gate covers fixed test packages on one MIUI 14 device only.",
        ],
    }


def apply_evidence_warnings(report: dict[str, Any], warnings: list[str]) -> None:
    report["warnings"] = warnings
    if not warnings:
        return
    report["safetyViolations"].extend(
        f"evidence warning: {warning}" for warning in warnings
    )
    report["safetyGatePassed"] = False
    report["provisionalDecision"] = (
        "STOP_S06_RESILIENCE_PATH" if report["sampleGatePassed"] else "NOT_READY"
    )


def _source_evidence(paths: Iterable[Path]) -> list[dict[str, str]]:
    return [
        {
            "file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        }
        for path in paths
    ]


def print_summary(report: dict[str, Any]) -> None:
    print("# Jump Terminator S0.6 resilience stress report")
    print()
    print(f"- Decision: **{report['provisionalDecision']}**")
    print(f"- Sample gate: {report['sampleGatePassed']}")
    print(f"- Safety gate: {report['safetyGatePassed']}")
    print(
        "- Crash cycles: "
        f"{report['crashStress']['observedCycles']}/{report['expected']['crashCycles']}",
    )
    print(
        "- Reauthorization cycles: "
        f"{report['reauthorizationStress']['observedCycles']}/"
        f"{report['expected']['reauthorizationCycles']}",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lifecycle", action="append", type=Path, required=True)
    parser.add_argument("--block-timeline", type=Path, required=True)
    parser.add_argument("--block-report", type=Path, required=True)
    parser.add_argument("--reauthorization", type=Path, required=True)
    parser.add_argument("--expected-crash-cycles", type=int, required=True)
    parser.add_argument("--expected-targets", type=int, required=True)
    parser.add_argument("--expected-reauthorization-cycles", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    arguments = parser.parse_args()

    lifecycle_events, lifecycle_warnings = load_lifecycle_events(arguments.lifecycle)
    reauthorization_events, reauthorization_warnings = load_reauthorization_events(
        arguments.reauthorization,
    )
    report = analyse(
        lifecycle_events,
        load_json(arguments.block_report),
        reauthorization_events,
        expected_crash_cycles=arguments.expected_crash_cycles,
        expected_targets=arguments.expected_targets,
        expected_reauthorization_cycles=arguments.expected_reauthorization_cycles,
    )
    all_paths = [
        *arguments.lifecycle,
        arguments.block_timeline,
        arguments.block_report,
        arguments.reauthorization,
    ]
    report["sourceEvidence"] = _source_evidence(all_paths)
    apply_evidence_warnings(
        report,
        [*lifecycle_warnings, *reauthorization_warnings],
    )
    print_summary(report)
    for warning in report["warnings"]:
        print(f"warning: {warning}")
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if arguments.strict and report["provisionalDecision"] != "S06_RESILIENCE_STRESS_PASSED":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
