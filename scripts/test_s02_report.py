import unittest

from scripts.s02_report import SOURCE_COMPONENT, TARGET_COMPONENT, analyse


def event(kind, session, sequence=0, time_ms=1_000, data=None):
    payload = dict(data or {})
    if sequence:
        payload.setdefault("sequence", sequence)
    return {
        "schema": "s0.2-1",
        "sessionId": session,
        "kind": kind,
        "wallClockMs": time_ms,
        "data": payload,
    }


def complete_block_session(count=100, executor=None):
    ready_data = {
        "scenario": "block",
        "mode": "armed",
        "requestedBlock": count,
        "requestedAllowed": 0,
    }
    if executor:
        ready_data["executor"] = executor
    if executor == "shizuku_user_service":
        ready_data.update(
            {
                "ownerBound": True,
                "crashGraceMs": 10_000,
                "ownerUserId": 0,
                "authorizationProtocol": "s0.4-1",
                "ownerUidSource": "binder",
                "ownerUid": 10_418,
                "ownerPackage": "com.jumpterminator.s02",
                "ownerSigningCertificateSha256": ["a" * 64],
                "oneTimeCapability": True,
                "capabilityFingerprint": "b" * 16,
                "ruleSnapshotSha256": "c" * 64,
                "leaseDurationMs": max(90_000, count * 8_000 + 60_000),
                "leaseDeadlineElapsedMs": 1_000_000,
                "finalActionSerialization": "authorization_lock",
            },
        )
    events = [
        event(
            "ready",
            "block",
            data=ready_data,
        ),
    ]
    for sequence in range(1, count + 1):
        base = sequence * 1_000
        events.extend(
            [
                event(
                    "target_detected",
                    "block",
                    sequence,
                    base,
                    {"detectionUpperBoundMs": 90, "pollDurationMs": 60},
                ),
                event(
                    "back_requested",
                    "block",
                    sequence,
                    base + 10,
                    {
                        "dispatched": True,
                        "sourceComponent": SOURCE_COMPONENT,
                        "targetComponent": TARGET_COMPONENT,
                        "requestUpperBoundMs": 100,
                        "inputDurationMs": 40,
                    },
                ),
                event(
                    "left_target",
                    "block",
                    sequence,
                    base + 100,
                    {"leftTarget": True, "returnedSource": True, "leaveUpperBoundMs": 190},
                ),
            ],
        )
    events.append(
        event(
            "complete",
            "block",
            time_ms=(count + 1) * 1_000,
            data={"reason": "count_reached", "detections": count, "actions": count},
        ),
    )
    return events


def allowed_session(count=15, executor=None):
    ready_data = {
        "scenario": "allowed-negative",
        "mode": "armed",
        "requestedBlock": 0,
        "requestedAllowed": count,
    }
    if executor:
        ready_data["executor"] = executor
    if executor == "shizuku_user_service":
        ready_data.update(
            {
                "ownerBound": True,
                "crashGraceMs": 10_000,
                "ownerUserId": 0,
                "authorizationProtocol": "s0.4-1",
                "ownerUidSource": "binder",
                "ownerUid": 10_418,
                "ownerPackage": "com.jumpterminator.s02",
                "ownerSigningCertificateSha256": ["a" * 64],
                "oneTimeCapability": True,
                "capabilityFingerprint": "d" * 16,
                "ruleSnapshotSha256": "e" * 64,
                "leaseDurationMs": max(90_000, count * 8_000 + 60_000),
                "leaseDeadlineElapsedMs": 1_000_000,
                "finalActionSerialization": "authorization_lock",
            },
        )
    events = [
        event(
            "ready",
            "allow",
            data=ready_data,
        ),
    ]
    for sequence in range(1, count + 1):
        events.append(
            event(
                "allowed_probe",
                "allow",
                sequence,
                200_000 + sequence,
                {"probeType": "settings", "passed": True},
            ),
        )
    events.append(
        event(
            "complete",
            "allow",
            time_ms=300_000,
            data={"reason": "stop_requested", "detections": 0, "actions": 0},
        ),
    )
    return events


class S02ReportTest(unittest.TestCase):
    def test_complete_upper_bound_gate_proceeds_to_shizuku(self):
        report = analyse(complete_block_session() + allowed_session())

        self.assertTrue(report["sampleGatePassed"])
        self.assertTrue(report["thresholdGatePassed"])
        self.assertEqual("PROCEED_TO_SHIZUKU_POC", report["provisionalDecision"])
        self.assertEqual(100, report["metrics"]["targetDetection"]["successes"])
        self.assertEqual(0, report["metrics"]["allowedFlowFalseBlock"]["successes"])
        self.assertEqual(100, report["latencyUpperBoundMs"]["backRequestP95"])

    def test_missing_realtime_detections_stops_completed_privileged_path(self):
        events = complete_block_session()
        events = [
            item
            for item in events
            if not (
                item["kind"] in {"target_detected", "back_requested", "left_target"}
                and (item.get("data") or {}).get("sequence", 0) > 90
            )
        ]
        report = analyse(events + allowed_session())

        self.assertTrue(report["sampleGatePassed"])
        self.assertFalse(report["thresholdGatePassed"])
        self.assertEqual("STOP_PRIVILEGED_PATH", report["provisionalDecision"])

    def test_complete_shizuku_gate_is_feasible_but_not_consumer_go(self):
        executor = "shizuku_user_service"
        report = analyse(
            complete_block_session(executor=executor)
            + allowed_session(executor=executor),
        )

        self.assertTrue(report["sampleGatePassed"])
        self.assertTrue(report["thresholdGatePassed"])
        self.assertEqual("SHIZUKU_POC_FEASIBLE", report["provisionalDecision"])
        self.assertEqual([executor], report["executors"])
        self.assertTrue(report["authorization"]["allSessionsOwnerBound"])
        self.assertTrue(report["authorization"]["allSessionsBinderDerived"])
        self.assertTrue(report["authorization"]["allSessionsSigningIdentityResolved"])
        self.assertTrue(report["authorization"]["allSessionsOneTimeCapability"])
        self.assertTrue(report["authorization"]["allSessionsRuleSnapshotBound"])
        self.assertEqual(["s0.4-1"], report["authorization"]["protocols"])
        self.assertEqual(
            ["authorization_lock"],
            report["authorization"]["finalActionSerializations"],
        )
        self.assertEqual([10_000], report["authorization"]["crashGraceMs"])
        self.assertEqual([0], report["authorization"]["ownerUserIds"])

    def test_incomplete_allowed_session_does_not_pass_sample_gate(self):
        events = complete_block_session() + allowed_session()
        events = [
            item
            for item in events
            if not (item["kind"] == "complete" and item["sessionId"] == "allow")
        ]
        report = analyse(events)

        self.assertFalse(report["allowedSessionsComplete"])
        self.assertFalse(report["sampleGatePassed"])

    def test_repeated_back_is_a_safety_violation(self):
        events = complete_block_session(1)
        events.append(
            event(
                "back_requested",
                "block",
                1,
                1_020,
                {
                    "dispatched": True,
                    "sourceComponent": SOURCE_COMPONENT,
                    "targetComponent": TARGET_COMPONENT,
                },
            ),
        )
        report = analyse(events)

        self.assertTrue(any("repeated Back" in item for item in report["safetyViolations"]))

    def test_any_action_in_allowed_session_is_a_false_block(self):
        events = allowed_session()
        events.extend(
            [
                event("target_detected", "allow", 1, 2_000),
                event(
                    "back_requested",
                    "allow",
                    1,
                    2_010,
                    {
                        "dispatched": True,
                        "sourceComponent": SOURCE_COMPONENT,
                        "targetComponent": TARGET_COMPONENT,
                    },
                ),
            ],
        )
        report = analyse(events)

        self.assertEqual(1, report["metrics"]["allowedFlowFalseBlock"]["successes"])
        self.assertTrue(any("allowed-negative" in item for item in report["safetyViolations"]))


if __name__ == "__main__":
    unittest.main()
