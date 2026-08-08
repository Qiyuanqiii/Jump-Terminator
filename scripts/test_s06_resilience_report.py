import unittest

from scripts.s06_resilience_report import analyse, apply_evidence_warnings


def lifecycle_event(session, kind, data):
    return {
        "schema": "s0.3-1",
        "sessionId": session,
        "scenario": "ui-kill",
        "kind": kind,
        "wallClockMs": 1_000,
        "data": data,
    }


def lifecycle_cycle(number):
    session = f"session-{number}"
    snapshot = {
        "bootId": "boot-a",
        "bootCompleted": True,
        "shizukuServerPid": 10,
        "companionPid": 20,
        "uiPid": 30,
        "sourcePid": 0,
        "targetPid": 0,
        "pocPackageUid": 10_418,
        "keyguardLocked": False,
    }
    result = {
        "ready": True,
        "detections": 1,
        "backs": 1,
        "dispatchedBacks": 1,
        "leaves": 1,
        "returnedSource": 1,
        "terminalKind": "complete",
        "terminalReason": "count_reached",
        "serviceErrors": 0,
        "timeouts": 0,
        "ownerDetachments": 1,
        "serviceExitRequests": 1,
        "authorizationProtocol": "s0.4-1",
        "ownerUidSource": "binder",
        "ownerUid": 10_418,
        "ownerUserId": 0,
        "ownerPackage": "com.jumpterminator.s02",
        "ownerSigningCertificateSha256": ["a" * 64],
        "oneTimeCapability": True,
        "capabilityFingerprint": "b" * 16,
        "ruleSnapshotSha256": "c" * 64,
        "leaseDurationMs": 90_000,
        "finalActionSerialization": "authorization_lock",
    }
    fault = dict(snapshot, uiPid=0)
    cleanup = dict(snapshot, shizukuServerPid=0, companionPid=0, uiPid=0)
    return [
        lifecycle_event(session, "scenario_started", {"model": "phone", "androidRelease": "13"}),
        lifecycle_event(session, "probe_ready", snapshot),
        lifecycle_event(session, "fault_injected", fault),
        lifecycle_event(session, "companion_result", result),
        lifecycle_event(session, "post_transition", snapshot),
        lifecycle_event(session, "scenario_complete", {"result": "observed"}),
        lifecycle_event(session, "cleanup_complete", cleanup),
    ]


def block_report(count=10):
    return {
        "schema": "s0.2-report-1",
        "executors": ["shizuku_user_service"],
        "warnings": [],
        "authorization": {
            "allSessionsBinderDerived": True,
            "allSessionsSigningIdentityResolved": True,
            "allSessionsOneTimeCapability": True,
            "allSessionsRuleSnapshotBound": True,
        },
        "sampleCounts": {
            "requestedBlock": count,
            "targetDetected": count,
            "backDispatched": count,
            "leftTarget": count,
            "returnedSource": count,
        },
        "blockSessionsComplete": True,
        "safetyViolations": [],
        "timeoutCount": 0,
        "failedEventCount": 0,
        "latencyUpperBoundMs": {"backRequestP95": 150},
    }


def reauthorization_events(cycles=3):
    events = []
    for cycle in range(1, cycles + 1):
        events.extend(
            [
                {
                    "schema": "s0.6-reauth-1",
                    "cycle": cycle,
                    "kind": "permission_revoked",
                    "granted": False,
                },
                {
                    "schema": "s0.6-reauth-1",
                    "cycle": cycle,
                    "kind": "revoked_probe",
                    "sessionId": f"{cycle:032x}",
                    "readyCount": 0,
                },
                {
                    "schema": "s0.6-reauth-1",
                    "cycle": cycle,
                    "kind": "permission_restored",
                    "granted": True,
                },
                {
                    "schema": "s0.6-reauth-1",
                    "cycle": cycle,
                    "kind": "recovered_probe",
                    "sessionId": f"{cycle + 100:032x}",
                    "readyCount": 1,
                },
            ]
        )
    return events


def complete_report():
    lifecycle = []
    for cycle in range(1, 6):
        lifecycle.extend(lifecycle_cycle(cycle))
    return analyse(
        lifecycle,
        block_report(),
        reauthorization_events(),
        expected_crash_cycles=5,
        expected_targets=10,
        expected_reauthorization_cycles=3,
    )


class S06ResilienceReportTest(unittest.TestCase):
    def test_complete_stress_matrix_passes(self):
        report = complete_report()

        self.assertTrue(report["sampleGatePassed"])
        self.assertTrue(report["safetyGatePassed"])
        self.assertEqual("S06_RESILIENCE_STRESS_PASSED", report["provisionalDecision"])

    def test_missing_crash_cycle_is_not_ready(self):
        lifecycle = []
        for cycle in range(1, 5):
            lifecycle.extend(lifecycle_cycle(cycle))
        report = analyse(
            lifecycle,
            block_report(),
            reauthorization_events(),
            expected_crash_cycles=5,
            expected_targets=10,
            expected_reauthorization_cycles=3,
        )

        self.assertFalse(report["sampleGatePassed"])
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_ready_while_permission_revoked_is_a_hard_stop(self):
        events = reauthorization_events()
        next(
            item
            for item in events
            if item["cycle"] == 2 and item["kind"] == "revoked_probe"
        )["readyCount"] = 1
        lifecycle = []
        for cycle in range(1, 6):
            lifecycle.extend(lifecycle_cycle(cycle))
        report = analyse(
            lifecycle,
            block_report(),
            events,
            expected_crash_cycles=5,
            expected_targets=10,
            expected_reauthorization_cycles=3,
        )

        self.assertTrue(report["sampleGatePassed"])
        self.assertFalse(report["safetyGatePassed"])
        self.assertEqual("STOP_S06_RESILIENCE_PATH", report["provisionalDecision"])

    def test_incomplete_repeated_target_session_is_a_hard_stop(self):
        incomplete = block_report()
        incomplete["sampleCounts"]["backDispatched"] = 9
        lifecycle = []
        for cycle in range(1, 6):
            lifecycle.extend(lifecycle_cycle(cycle))
        report = analyse(
            lifecycle,
            incomplete,
            reauthorization_events(),
            expected_crash_cycles=5,
            expected_targets=10,
            expected_reauthorization_cycles=3,
        )

        self.assertFalse(report["safetyGatePassed"])
        self.assertEqual("STOP_S06_RESILIENCE_PATH", report["provisionalDecision"])

    def test_duplicate_reauthorization_event_is_a_hard_stop(self):
        events = reauthorization_events()
        events.insert(2, dict(events[1]))
        lifecycle = []
        for cycle in range(1, 6):
            lifecycle.extend(lifecycle_cycle(cycle))
        report = analyse(
            lifecycle,
            block_report(),
            events,
            expected_crash_cycles=5,
            expected_targets=10,
            expected_reauthorization_cycles=3,
        )

        self.assertFalse(report["reauthorizationStress"]["gatePassed"])
        self.assertEqual("STOP_S06_RESILIENCE_PATH", report["provisionalDecision"])

    def test_reused_probe_session_id_is_a_hard_stop(self):
        events = reauthorization_events()
        first_revoked = next(
            item
            for item in events
            if item["cycle"] == 1 and item["kind"] == "revoked_probe"
        )
        second_revoked = next(
            item
            for item in events
            if item["cycle"] == 2 and item["kind"] == "revoked_probe"
        )
        second_revoked["sessionId"] = first_revoked["sessionId"]
        lifecycle = []
        for cycle in range(1, 6):
            lifecycle.extend(lifecycle_cycle(cycle))
        report = analyse(
            lifecycle,
            block_report(),
            events,
            expected_crash_cycles=5,
            expected_targets=10,
            expected_reauthorization_cycles=3,
        )

        self.assertFalse(
            report["reauthorizationStress"]["allProbeSessionIdsUnique"]
        )
        self.assertEqual("STOP_S06_RESILIENCE_PATH", report["provisionalDecision"])

    def test_evidence_warning_is_a_hard_stop(self):
        report = complete_report()

        apply_evidence_warnings(report, ["timeline: invalid JSON"])

        self.assertFalse(report["safetyGatePassed"])
        self.assertEqual("STOP_S06_RESILIENCE_PATH", report["provisionalDecision"])


if __name__ == "__main__":
    unittest.main()
