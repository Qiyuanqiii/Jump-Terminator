#!/usr/bin/env python3
"""Aggregate Jump Terminator S0.3 lifecycle fault-injection evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "s0.3-1"
REPORT_SCHEMA = "s0.3-report-2"
REQUIRED_SCENARIOS = (
    "ui-kill",
    "ui-force-stop",
    "shizuku-graceful-stop",
    "shizuku-disconnect",
    "disconnect-recovery",
    "reboot",
    "post-reboot-recovery",
)
PROCESS_FIELDS = (
    "shizukuServerPid",
    "companionPid",
    "uiPid",
    "sourcePid",
    "targetPid",
)
ACTION_SCENARIOS = {
    "ui-kill",
    "disconnect-recovery",
    "post-reboot-recovery",
}
FAIL_OPEN_SCENARIOS = {
    "shizuku-graceful-stop",
    "shizuku-disconnect",
}
S04_DIGEST = re.compile(r"^[a-f0-9]{64}$")
S04_FINGERPRINT = re.compile(r"^[a-f0-9]{16}$")


def load_events(paths: Iterable[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError as error:
            warnings.append(f"{path}: unable to read: {error}")
            continue
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                warnings.append(f"{path}:{line_number}: invalid JSON: {error.msg}")
                continue
            if not isinstance(event, dict) or event.get("schema") != SCHEMA:
                warnings.append(f"{path}:{line_number}: unsupported schema")
                continue
            events.append(event)
    return events, warnings


def _event_data(events: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    matches = [event.get("data") or {} for event in events if event.get("kind") == kind]
    return matches[-1] if matches else None


def _positive(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _zero(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def _cleanup_ok(data: dict[str, Any] | None) -> bool:
    return bool(data) and all(_zero(data.get(field)) for field in PROCESS_FIELDS)


def _one_action_ok(data: dict[str, Any] | None) -> bool:
    if not data:
        return False
    return (
        data.get("ready") is True
        and data.get("detections") == 1
        and data.get("backs") == 1
        and data.get("dispatchedBacks") == 1
        and data.get("leaves") == 1
        and data.get("returnedSource") == 1
        and data.get("terminalKind") == "complete"
        and data.get("terminalReason") == "count_reached"
        and data.get("serviceErrors") == 0
        and data.get("timeouts") == 0
    )


def _no_action_ok(data: dict[str, Any] | None) -> bool:
    if not data:
        return False
    return (
        data.get("ready") is True
        and data.get("detections") == 0
        and data.get("backs") == 0
        and data.get("dispatchedBacks") == 0
        and data.get("leaves") == 0
        and data.get("returnedSource") == 0
        and data.get("serviceErrors") == 0
        and data.get("timeouts") == 0
    )


def _common_checks(events: list[dict[str, Any]]) -> dict[str, bool]:
    completed = _event_data(events, "scenario_complete")
    cleanup = _event_data(events, "cleanup_complete")
    return {
        "scenarioCompleted": bool(completed and completed.get("result") == "observed"),
        "runnerErrorFree": not any(event.get("kind") == "runner_error" for event in events),
        "cleanupStoppedAllTestProcesses": _cleanup_ok(cleanup),
    }


def _evaluate_session(
    session_id: str,
    scenario: str,
    events: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    checks = _common_checks(events)
    violations: list[str] = []
    probe = _event_data(events, "probe_ready")
    fault = _event_data(events, "fault_injected")
    result = _event_data(events, "companion_result")

    if scenario == "reboot":
        before = _event_data(events, "pre_reboot")
        after = _event_data(events, "post_reboot")
        checks.update(
            {
                "bootIdChanged": bool(
                    before
                    and after
                    and before.get("bootId")
                    and after.get("bootId")
                    and before.get("bootId") != after.get("bootId")
                ),
                "bootCompleted": bool(after and after.get("bootCompleted") is True),
                "coldStartHadNoPrivilegedOrTestProcesses": bool(
                    after and all(_zero(after.get(field)) for field in PROCESS_FIELDS)
                ),
            }
        )
    else:
        checks.update(
            {
                "probeHadShizukuServer": bool(probe and _positive(probe.get("shizukuServerPid"))),
                "probeHadCompanion": bool(probe and _positive(probe.get("companionPid"))),
                "probeHadUi": bool(probe and _positive(probe.get("uiPid"))),
            }
        )
        if result and result.get("authorizationProtocol") is not None:
            signers = result.get("ownerSigningCertificateSha256")
            capability_fingerprint = str(result.get("capabilityFingerprint") or "")
            rule_snapshot = str(result.get("ruleSnapshotSha256") or "")
            checks.update(
                {
                    "authorizationProtocolIsS04": result.get("authorizationProtocol")
                    == "s0.4-1",
                    "ownerUidWasBinderDerived": result.get("ownerUidSource") == "binder",
                    "ownerUidMatchesPackage": bool(
                        probe
                        and isinstance(probe.get("pocPackageUid"), int)
                        and result.get("ownerUid") == probe.get("pocPackageUid")
                    ),
                    "ownerPackageIsFixed": result.get("ownerPackage")
                    == "com.jumpterminator.s02",
                    "ownerSigningIdentityResolved": isinstance(signers, list)
                    and bool(signers)
                    and all(
                        isinstance(item, str) and S04_DIGEST.fullmatch(item)
                        for item in signers
                    ),
                    "oneTimeCapabilityBound": result.get("oneTimeCapability") is True,
                    "capabilityFingerprintIsRedacted": bool(
                        S04_FINGERPRINT.fullmatch(capability_fingerprint)
                    ),
                    "ruleSnapshotIsBound": bool(S04_DIGEST.fullmatch(rule_snapshot)),
                    "authorizationLeaseIsBounded": isinstance(
                        result.get("leaseDurationMs"),
                        (int, float),
                    )
                    and 0 < int(result.get("leaseDurationMs")) <= 900_000,
                    "finalActionIsSerialized": result.get("finalActionSerialization")
                    == "authorization_lock",
                }
            )

    if scenario == "ui-kill":
        checks.update(
            {
                "uiProcessCrashed": bool(fault and _zero(fault.get("uiPid"))),
                "companionSurvivedUiCrash": bool(fault and _positive(fault.get("companionPid"))),
                "serverSurvivedUiCrash": bool(fault and _positive(fault.get("shizukuServerPid"))),
                "boundedActionCompletedAfterUiCrash": _one_action_ok(result),
            }
        )
    elif scenario == "ui-force-stop":
        dispatched = (result or {}).get("dispatchedBacks")
        authorization_reasons = (result or {}).get("authorizationReasons") or []
        checks.update(
            {
                "uiPackageWasForceStopped": bool(fault and _zero(fault.get("uiPid"))),
                "companionStateWasObserved": bool(fault and "companionPid" in fault),
                "companionStoppedAfterForceStop": bool(
                    fault and _zero(fault.get("companionPid"))
                ),
                "ownerAuthorizationWasRevoked": bool(
                    (result or {}).get("authorizationRevocations", 0) >= 1
                    and "owner_package_stopped" in authorization_reasons
                ),
                "noPrivilegedActionAfterForceStop": dispatched == 0,
            }
        )
        if isinstance(dispatched, int) and dispatched > 0:
            violations.append(
                f"{scenario}#{session_id}: dispatched {dispatched} privileged Back action(s) "
                "after explicit package force-stop"
            )
    elif scenario in FAIL_OPEN_SCENARIOS:
        checks.update(
            {
                "shizukuServerStopped": bool(fault and _zero(fault.get("shizukuServerPid"))),
                "companionStoppedWithServer": bool(fault and _zero(fault.get("companionPid"))),
                "testTransitionWasLaunched": bool(
                    (_event_data(events, "post_transition") or {}).get("targetPid", 0) > 0
                ),
                "failedOpenWithoutPrivilegedAction": _no_action_ok(result),
            }
        )
        dispatched = (result or {}).get("dispatchedBacks")
        if isinstance(dispatched, int) and dispatched > 0:
            violations.append(
                f"{scenario}#{session_id}: dispatched {dispatched} privileged Back action(s) "
                "after Shizuku loss"
            )
    elif scenario in {"disconnect-recovery", "post-reboot-recovery"}:
        checks["grantBindAndActionRecovered"] = _one_action_ok(result)

    if not checks.get("runnerErrorFree", False):
        violations.append(f"{scenario}#{session_id}: runner_error was recorded")
    if not checks.get("cleanupStoppedAllTestProcesses", False):
        violations.append(f"{scenario}#{session_id}: cleanup left a test or privileged process alive")

    structural_checks = [
        checks.get("scenarioCompleted", False),
        checks.get("runnerErrorFree", False),
    ]
    if scenario == "reboot":
        structural_checks.extend(
            [
                _event_data(events, "pre_reboot") is not None,
                _event_data(events, "post_reboot") is not None,
                checks.get("bootIdChanged", False),
                checks.get("bootCompleted", False),
            ]
        )
    else:
        structural_checks.extend(
            [
                probe is not None,
                fault is not None,
                result is not None,
                checks.get("probeHadShizukuServer", False),
                checks.get("probeHadCompanion", False),
                checks.get("probeHadUi", False),
            ]
        )
        if scenario == "ui-kill":
            structural_checks.append(checks.get("uiProcessCrashed", False))
        elif scenario == "ui-force-stop":
            structural_checks.append(checks.get("uiPackageWasForceStopped", False))
        elif scenario in FAIL_OPEN_SCENARIOS:
            structural_checks.extend(
                [
                    checks.get("shizukuServerStopped", False),
                    checks.get("testTransitionWasLaunched", False),
                ]
            )
    observation_valid = all(structural_checks)
    gate_passed = all(checks.values())
    return (
        {
            "sessionId": session_id,
            "scenario": scenario,
            "eventCount": len(events),
            "observationValid": observation_valid,
            "gatePassed": gate_passed,
            "checks": checks,
            "observed": {
                "probe": probe,
                "fault": fault,
                "companionResult": result,
                "preReboot": _event_data(events, "pre_reboot"),
                "postReboot": _event_data(events, "post_reboot"),
                "cleanup": _event_data(events, "cleanup_complete"),
            },
        },
        violations,
    )


def analyse(events: list[dict[str, Any]]) -> dict[str, Any]:
    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        sessions[str(event.get("sessionId") or "unknown")].append(event)

    evaluations: list[dict[str, Any]] = []
    violations: list[str] = []
    inconsistent_sessions: list[str] = []
    for session_id, session_events in sorted(sessions.items()):
        scenarios = {
            str(event.get("scenario"))
            for event in session_events
            if event.get("scenario") is not None
        }
        if len(scenarios) != 1:
            inconsistent_sessions.append(session_id)
            violations.append(f"session {session_id}: inconsistent or missing scenario")
            continue
        scenario = next(iter(scenarios))
        evaluation, session_violations = _evaluate_session(session_id, scenario, session_events)
        evaluations.append(evaluation)
        violations.extend(session_violations)

    by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for evaluation in evaluations:
        by_scenario[evaluation["scenario"]].append(evaluation)

    coverage = {
        scenario: any(item["observationValid"] for item in by_scenario.get(scenario, []))
        for scenario in REQUIRED_SCENARIOS
    }
    missing_or_invalid = [scenario for scenario, passed in coverage.items() if not passed]
    sample_gate = not missing_or_invalid and not inconsistent_sessions

    force_stop_safe = any(
        item["gatePassed"] for item in by_scenario.get("ui-force-stop", [])
    )
    shizuku_loss_safe = all(
        any(item["gatePassed"] for item in by_scenario.get(scenario, []))
        for scenario in FAIL_OPEN_SCENARIOS
    )
    reboot_safe = any(
        item["gatePassed"] for item in by_scenario.get("reboot", [])
    )
    recovery_gate = all(
        any(item["gatePassed"] for item in by_scenario.get(scenario, []))
        for scenario in ("disconnect-recovery", "post-reboot-recovery")
    )
    ui_crash_resilience = any(
        item["gatePassed"] for item in by_scenario.get("ui-kill", [])
    )
    s04_evaluations = [
        item
        for item in evaluations
        if item["scenario"] != "reboot"
        and "authorizationProtocolIsS04" in item["checks"]
    ]
    s04_required_scenarios = {
        scenario for scenario in REQUIRED_SCENARIOS if scenario != "reboot"
    }
    s04_covered_scenarios = {
        item["scenario"] for item in s04_evaluations if item["observationValid"]
    }
    s04_authorization_gate = (
        s04_covered_scenarios == s04_required_scenarios
        and all(
            all(
                value
                for name, value in item["checks"].items()
                if name
                in {
                    "authorizationProtocolIsS04",
                    "ownerUidWasBinderDerived",
                    "ownerUidMatchesPackage",
                    "ownerPackageIsFixed",
                    "ownerSigningIdentityResolved",
                    "oneTimeCapabilityBound",
                    "capabilityFingerprintIsRedacted",
                    "ruleSnapshotIsBound",
                    "authorizationLeaseIsBounded",
                    "finalActionIsSerialized",
                }
            )
            for item in s04_evaluations
        )
        if s04_evaluations
        else None
    )
    safety_gate = (
        sample_gate
        and force_stop_safe
        and shizuku_loss_safe
        and reboot_safe
        and not violations
    )

    if not sample_gate:
        decision = "NOT_READY"
    elif not force_stop_safe:
        decision = "STOP_UNTIL_FORCE_STOP_FAIL_SAFE"
    elif not safety_gate or not recovery_gate or not ui_crash_resilience:
        decision = "STOP_LIFECYCLE_PATH"
    else:
        decision = "LIFECYCLE_GATE_PASSED"

    wall_clocks = [
        int(event["wallClockMs"])
        for event in events
        if isinstance(event.get("wallClockMs"), (int, float))
    ]
    device_models = sorted(
        {
            str((event.get("data") or {}).get("model"))
            for event in events
            if event.get("kind") == "scenario_started"
            and (event.get("data") or {}).get("model")
        }
    )
    android_releases = sorted(
        {
            str((event.get("data") or {}).get("androidRelease"))
            for event in events
            if event.get("kind") == "scenario_started"
            and (event.get("data") or {}).get("androidRelease")
        }
    )

    return {
        "schema": REPORT_SCHEMA,
        "eventCount": len(events),
        "sessionCount": len(sessions),
        "requiredScenarios": list(REQUIRED_SCENARIOS),
        "scenarioCoverage": coverage,
        "missingOrInvalidScenarios": missing_or_invalid,
        "sessions": evaluations,
        "device": {
            "models": device_models,
            "androidReleases": android_releases,
        },
        "wallClockRangeMs": {
            "first": min(wall_clocks) if wall_clocks else None,
            "last": max(wall_clocks) if wall_clocks else None,
        },
        "sampleGatePassed": sample_gate,
        "forceStopFailSafePassed": force_stop_safe,
        "shizukuLossFailSafePassed": shizuku_loss_safe,
        "rebootColdStartSafePassed": reboot_safe,
        "recoveryGatePassed": recovery_gate,
        "uiCrashResiliencePassed": ui_crash_resilience,
        "s04AuthorizationEvidenceSessions": len(s04_evaluations),
        "s04AuthorizationScenarioCoverage": {
            scenario: scenario in s04_covered_scenarios
            for scenario in sorted(s04_required_scenarios)
        },
        "s04AuthorizationGatePassed": s04_authorization_gate,
        "safetyGatePassed": safety_gate,
        "safetyViolations": violations,
        "provisionalDecision": decision,
        "notes": [
            "UI crash continuation is a resilience observation, not authorization for an unbounded daemon.",
            "An explicit package force-stop is treated as a user stop signal; privileged actions must cease.",
            "Shizuku loss is required to fail open: the test transition may continue, but no Back may be sent.",
            "This lifecycle gate covers one MIUI 14 device and fixed test packages only.",
        ],
    }


def _source_evidence(paths: Iterable[Path]) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    for path in paths:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        except OSError:
            continue
        evidence.append({"file": path.name, "sha256": digest})
    return evidence


def print_summary(report: dict[str, Any]) -> None:
    print("# Jump Terminator S0.3 lifecycle report")
    print()
    print(f"- Decision: **{report['provisionalDecision']}**")
    print(f"- Evidence coverage: {report['sampleGatePassed']}")
    print(f"- Safety gate: {report['safetyGatePassed']}")
    print(f"- Recovery gate: {report['recoveryGatePassed']}")
    print()
    print("| Scenario | Evidence | Gate |")
    print("| --- | ---: | ---: |")
    for scenario in REQUIRED_SCENARIOS:
        matching = [item for item in report["sessions"] if item["scenario"] == scenario]
        observed = any(item["observationValid"] for item in matching)
        passed = any(item["gatePassed"] for item in matching)
        print(f"| {scenario} | {observed} | {passed} |")
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
    report["sourceEvidence"] = _source_evidence(arguments.timeline)
    report["warnings"] = warnings
    if report["wallClockRangeMs"]["last"] is not None:
        report["evidenceCompletedAt"] = datetime.fromtimestamp(
            report["wallClockRangeMs"]["last"] / 1000,
            tz=timezone.utc,
        ).isoformat().replace("+00:00", "Z")
    print_summary(report)
    for warning in warnings:
        print(f"warning: {warning}")
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if arguments.strict and report["provisionalDecision"] != "LIFECYCLE_GATE_PASSED":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
