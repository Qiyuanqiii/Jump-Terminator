import unittest

from scripts.s03_lifecycle_report import REQUIRED_SCENARIOS, analyse


def event(scenario, kind, data=None, session=None, time_ms=1_000):
    return {
        "schema": "s0.3-1",
        "sessionId": session or scenario,
        "scenario": scenario,
        "kind": kind,
        "wallClockMs": time_ms,
        "data": dict(data or {}),
    }


def snapshot(server=10, companion=20, ui=30, source=0, target=0, boot="boot-a"):
    return {
        "bootId": boot,
        "bootCompleted": True,
        "shizukuServerPid": server,
        "companionPid": companion,
        "uiPid": ui,
        "sourcePid": source,
        "targetPid": target,
        "keyguardLocked": False,
        "pocPackageUid": 10_418,
    }


def action_result(actions=1):
    if actions:
        return {
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
            "authorizationRevocations": 0,
            "authorizationReasons": [],
            "ownerDetachments": 0,
            "serviceExitRequests": 0,
        }
    return {
        "ready": True,
        "detections": 0,
        "backs": 0,
        "dispatchedBacks": 0,
        "leaves": 0,
        "returnedSource": 0,
        "terminalKind": None,
        "terminalReason": None,
        "serviceErrors": 0,
        "timeouts": 0,
        "authorizationRevocations": 0,
        "authorizationReasons": [],
        "ownerDetachments": 0,
        "serviceExitRequests": 0,
    }


def scenario_events(scenario, force_stop_actions=0, s04=False):
    events = [
        event(scenario, "scenario_started", {"model": "phone", "androidRelease": "13"}),
    ]
    if scenario == "reboot":
        events.extend(
            [
                event(scenario, "pre_reboot", snapshot(server=0, companion=0, ui=0)),
                event(
                    scenario,
                    "post_reboot",
                    snapshot(server=0, companion=0, ui=0, boot="boot-b"),
                ),
            ]
        )
    else:
        events.append(event(scenario, "probe_ready", snapshot()))
        if scenario == "ui-kill":
            fault = snapshot(ui=0)
            result = action_result(1)
        elif scenario == "ui-force-stop":
            fault = snapshot(ui=0, companion=20 if force_stop_actions else 0)
            result = action_result(force_stop_actions)
            if not force_stop_actions:
                result.update(
                    {
                        "authorizationRevocations": 1,
                        "authorizationReasons": ["owner_package_stopped"],
                        "serviceExitRequests": 1,
                    }
                )
        elif scenario in {"shizuku-graceful-stop", "shizuku-disconnect"}:
            fault = snapshot(server=0, companion=0)
            result = action_result(0)
        else:
            fault = snapshot()
            result = action_result(1)
        if s04:
            result.update(
                {
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
            )
        events.extend(
            [
                event(scenario, "fault_injected", fault),
                event(scenario, "companion_result", result),
                event(scenario, "post_transition", snapshot(source=40, target=50)),
            ]
        )
    events.extend(
        [
            event(scenario, "scenario_complete", {"result": "observed"}),
            event(scenario, "cleanup_complete", snapshot(server=0, companion=0, ui=0)),
        ]
    )
    return events


def complete_matrix(force_stop_actions=0, s04=False):
    events = []
    for scenario in REQUIRED_SCENARIOS:
        events.extend(
            scenario_events(
                scenario,
                force_stop_actions=force_stop_actions,
                s04=s04,
            )
        )
    return events


class S03LifecycleReportTest(unittest.TestCase):
    def test_complete_fail_safe_matrix_passes(self):
        report = analyse(complete_matrix())

        self.assertTrue(report["sampleGatePassed"])
        self.assertTrue(report["forceStopFailSafePassed"])
        self.assertTrue(report["shizukuLossFailSafePassed"])
        self.assertTrue(report["rebootColdStartSafePassed"])
        self.assertTrue(report["recoveryGatePassed"])
        self.assertTrue(report["safetyGatePassed"])
        self.assertEqual("LIFECYCLE_GATE_PASSED", report["provisionalDecision"])

    def test_action_after_force_stop_is_a_hard_stop(self):
        report = analyse(complete_matrix(force_stop_actions=1))

        self.assertTrue(report["sampleGatePassed"])
        self.assertFalse(report["forceStopFailSafePassed"])
        self.assertFalse(report["safetyGatePassed"])
        self.assertEqual(
            "STOP_UNTIL_FORCE_STOP_FAIL_SAFE",
            report["provisionalDecision"],
        )
        self.assertTrue(any("after explicit package force-stop" in item for item in report["safetyViolations"]))

    def test_action_after_shizuku_loss_fails_safety_gate(self):
        events = complete_matrix()
        for item in events:
            if item["scenario"] == "shizuku-disconnect" and item["kind"] == "companion_result":
                item["data"] = action_result(1)
        report = analyse(events)

        self.assertFalse(report["shizukuLossFailSafePassed"])
        self.assertFalse(report["safetyGatePassed"])
        self.assertEqual("STOP_LIFECYCLE_PATH", report["provisionalDecision"])

    def test_missing_required_scenario_is_not_ready(self):
        events = [
            item
            for item in complete_matrix()
            if item["scenario"] != "post-reboot-recovery"
        ]
        report = analyse(events)

        self.assertFalse(report["sampleGatePassed"])
        self.assertIn("post-reboot-recovery", report["missingOrInvalidScenarios"])
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_s04_identity_evidence_is_checked_for_non_reboot_sessions(self):
        report = analyse(complete_matrix(s04=True))

        self.assertEqual(6, report["s04AuthorizationEvidenceSessions"])
        self.assertTrue(report["s04AuthorizationGatePassed"])

    def test_partial_s04_identity_evidence_does_not_pass_s04_gate(self):
        events = complete_matrix(s04=True)
        for item in events:
            if (
                item["scenario"] == "ui-kill"
                and item["kind"] == "companion_result"
            ):
                item["data"].pop("authorizationProtocol")

        report = analyse(events)

        self.assertEqual(5, report["s04AuthorizationEvidenceSessions"])
        self.assertFalse(report["s04AuthorizationGatePassed"])


if __name__ == "__main__":
    unittest.main()
