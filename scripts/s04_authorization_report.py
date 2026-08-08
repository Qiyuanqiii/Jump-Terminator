#!/usr/bin/env python3
"""Build the S0.4 server-derived authorization and replay-safety report."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.s02_report import analyse as analyse_s02
    from scripts.s02_report import load_events
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from s02_report import analyse as analyse_s02
    from s02_report import load_events


REPORT_SCHEMA = "s0.4-authorization-report-1"
OWNER_PACKAGE = "com.jumpterminator.s02"
PROTOCOL = "s0.4-1"
DIGEST_64 = re.compile(r"^[a-f0-9]{64}$")
FINGERPRINT_16 = re.compile(r"^[a-f0-9]{16}$")


def _has_raw_capability(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"capability", "capabilitySecret", "capabilityNonce"}:
                return True
            if _has_raw_capability(child):
                return True
    elif isinstance(value, list):
        return any(_has_raw_capability(child) for child in value)
    return False


def analyse(events: list[dict[str, Any]]) -> dict[str, Any]:
    performance = analyse_s02(events)
    ready_events = [event for event in events if event.get("kind") == "ready"]
    expected_events = {
        str(event.get("sessionId")): event
        for event in events
        if event.get("kind") == "owner_identity_expected"
    }

    sessions: list[dict[str, Any]] = []
    fingerprints: list[str] = []
    rule_hashes: list[str] = []
    for ready in ready_events:
        session_id = str(ready.get("sessionId") or "unknown")
        data = ready.get("data") or {}
        expected = (expected_events.get(session_id) or {}).get("data") or {}
        signers = data.get("ownerSigningCertificateSha256")
        fingerprint = str(data.get("capabilityFingerprint") or "")
        rule_hash = str(data.get("ruleSnapshotSha256") or "")
        if fingerprint:
            fingerprints.append(fingerprint)
        if rule_hash:
            rule_hashes.append(rule_hash)
        checks = {
            "protocolIsS04": data.get("authorizationProtocol") == PROTOCOL,
            "uidWasBinderDerived": data.get("ownerUidSource") == "binder",
            "ownerPackageIsFixed": data.get("ownerPackage") == OWNER_PACKAGE,
            "ownerUidMatchesPackage": isinstance(expected.get("packageUid"), int)
            and data.get("ownerUid") == expected.get("packageUid"),
            "ownerPackageMatchesExpectation": expected.get("packageName") == OWNER_PACKAGE,
            "signingIdentityResolved": isinstance(signers, list)
            and bool(signers)
            and all(isinstance(item, str) and DIGEST_64.fullmatch(item) for item in signers),
            "oneTimeCapabilityDeclared": data.get("oneTimeCapability") is True,
            "capabilityFingerprintIsRedacted": bool(FINGERPRINT_16.fullmatch(fingerprint)),
            "ruleSnapshotIsBound": bool(DIGEST_64.fullmatch(rule_hash)),
            "leaseIsBounded": isinstance(data.get("leaseDurationMs"), (int, float))
            and 0 < int(data.get("leaseDurationMs")) <= 900_000,
            "leaseDeadlinePresent": isinstance(
                data.get("leaseDeadlineElapsedMs"),
                (int, float),
            ),
            "finalActionIsSerialized": data.get("finalActionSerialization")
            == "authorization_lock",
        }
        sessions.append(
            {
                "sessionId": session_id,
                "scenario": data.get("scenario"),
                "checks": checks,
                "gatePassed": all(checks.values()),
                "observed": {
                    "ownerUid": data.get("ownerUid"),
                    "ownerUserId": data.get("ownerUserId"),
                    "ownerPackage": data.get("ownerPackage"),
                    "signingCertificateSha256": signers,
                    "capabilityFingerprint": fingerprint,
                    "ruleSnapshotSha256": rule_hash,
                    "leaseDurationMs": data.get("leaseDurationMs"),
                },
            },
        )

    actions_after_revocation: list[str] = []
    revoked_at: dict[str, int] = {}
    for event in events:
        session_id = str(event.get("sessionId") or "unknown")
        wall_clock_ms = int(event.get("wallClockMs") or 0)
        if event.get("kind") == "authorization_revoked":
            revoked_at[session_id] = min(revoked_at.get(session_id, wall_clock_ms), wall_clock_ms)
        elif event.get("kind") == "back_requested" and session_id in revoked_at:
            if wall_clock_ms >= revoked_at[session_id]:
                actions_after_revocation.append(session_id)

    security_checks = {
        "hasAuthorizationEvidence": bool(ready_events),
        "allSessionsPassed": bool(sessions) and all(item["gatePassed"] for item in sessions),
        "capabilityFingerprintsUnique": len(fingerprints) == len(set(fingerprints)),
        "ruleSnapshotsUnique": len(rule_hashes) == len(set(rule_hashes)),
        "noRawCapabilityFields": not any(_has_raw_capability(event) for event in events),
        "noActionsAfterRevocation": not actions_after_revocation,
        "noRunnerOrServiceErrors": not any(
            event.get("kind") in {"runner_error", "service_error"} for event in events
        ),
    }
    security_gate = all(security_checks.values())
    performance_gate = bool(
        performance.get("sampleGatePassed")
        and performance.get("thresholdGatePassed")
        and (performance.get("latencyUpperBoundMs") or {}).get("backRequestP95") is not None
        and int(performance["latencyUpperBoundMs"]["backRequestP95"]) <= 250
    )
    if security_gate and performance_gate:
        decision = "S04_AUTHORIZATION_GATE_PASSED"
    elif security_gate:
        decision = "S04_SECURITY_SMOKE_PASSED"
    else:
        decision = "STOP_S04_AUTHORIZATION"

    return {
        "schema": REPORT_SCHEMA,
        "sessionCount": len(ready_events),
        "sessions": sessions,
        "securityChecks": security_checks,
        "securityGatePassed": security_gate,
        "performanceGatePassed": performance_gate,
        "performance": {
            "sampleGatePassed": performance.get("sampleGatePassed"),
            "thresholdGatePassed": performance.get("thresholdGatePassed"),
            "decision": performance.get("provisionalDecision"),
            "sampleCounts": performance.get("sampleCounts"),
            "latencyUpperBoundMs": performance.get("latencyUpperBoundMs"),
        },
        "actionsAfterRevocation": sorted(set(actions_after_revocation)),
        "provisionalDecision": decision,
        "notes": [
            "The gate covers the fixed-package Shizuku PoC and does not authorize consumer release.",
            "The local serialization point cannot make Android package stopped state and input injection one system transaction.",
            "Raw capability values are forbidden from events and public evidence.",
        ],
    }


def _source_evidence(paths: Iterable[Path]) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    for path in paths:
        evidence.append(
            {
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
            },
        )
    return evidence


def print_summary(report: dict[str, Any]) -> None:
    print("# Jump Terminator S0.4 authorization report")
    print()
    print(f"- Decision: **{report['provisionalDecision']}**")
    print(f"- Security gate: {report['securityGatePassed']}")
    print(f"- Performance gate: {report['performanceGatePassed']}")
    print(f"- Sessions: {report['sessionCount']}")
    for name, value in report["securityChecks"].items():
        print(f"- {name}: {value}")


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
    print_summary(report)
    for warning in warnings:
        print(f"warning: {warning}")
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if arguments.strict and report["provisionalDecision"] != "S04_AUTHORIZATION_GATE_PASSED":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
