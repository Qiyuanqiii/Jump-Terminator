import unittest

from scripts.s07_device_state_report import analyse, apply_warnings


SOURCE = "com.jumpterminator.testsource/.SourceActivity"
TARGET = "com.jumpterminator.testtarget/.TargetActivity"


def wrapper(scenario, cycle, session, kind, data=None):
    return {
        "schema": "s0.7-1",
        "scenario": scenario,
        "cycle": cycle,
        "sessionId": session,
        "kind": kind,
        "wallClockMs": cycle * 1_000,
        "data": data or {},
    }


def companion(scenario, cycle, session, kind, data=None):
    return wrapper(
        scenario,
        cycle,
        session,
        "companion_event",
        {
            "event": {
                "schema": "s0.2-1",
                "sessionId": session,
                "kind": kind,
                "wallClockMs": cycle * 1_000,
                "data": data or {},
            }
        },
    )


def session_events(scenario, cycle):
    prefix = {"recents": 1, "split-screen": 2, "screen-lock": 3}[scenario]
    session = f"{prefix * 100 + cycle:032x}"
    events = [
        wrapper(scenario, cycle, session, "scenario_started"),
        companion(scenario, cycle, session, "ready"),
        companion(
            scenario,
            cycle,
            session,
            "foreground_changed",
            {"state": "source", "resumedComponents": [SOURCE]},
        ),
        wrapper(scenario, cycle, session, "source_observed"),
    ]
    if scenario == "recents":
        events.extend(
            [
                companion(
                    scenario,
                    cycle,
                    session,
                    "source_context_invalidated",
                    {"reason": "foreground_changed"},
                ),
                wrapper(
                    scenario,
                    cycle,
                    session,
                    "boundary_injected",
                    {"topResumedComponents": ["com.miui.home/.launcher.Launcher"]},
                ),
                companion(
                    scenario,
                    cycle,
                    session,
                    "foreground_changed",
                    {"state": "target", "component": TARGET, "resumedComponents": [TARGET]},
                ),
            ]
        )
    elif scenario == "split-screen":
        events.extend(
            [
                companion(
                    scenario,
                    cycle,
                    session,
                    "foreground_changed",
                    {"state": "ambiguous", "resumedComponents": [TARGET, SOURCE]},
                ),
                companion(
                    scenario,
                    cycle,
                    session,
                    "source_context_invalidated",
                    {"reason": "foreground_ambiguous"},
                ),
                wrapper(scenario, cycle, session, "boundary_injected"),
            ]
        )
    else:
        events.extend(
            [
                companion(
                    scenario,
                    cycle,
                    session,
                    "source_context_invalidated",
                    {"reason": "device_not_interactive"},
                ),
                wrapper(
                    scenario,
                    cycle,
                    session,
                    "boundary_injected",
                    {"interactive": False, "keyguardLocked": True},
                ),
                wrapper(
                    scenario,
                    cycle,
                    session,
                    "recovery_observed",
                    {"interactive": True, "keyguardLocked": False},
                ),
                companion(
                    scenario,
                    cycle,
                    session,
                    "foreground_changed",
                    {"state": "target", "component": TARGET, "resumedComponents": [TARGET]},
                ),
            ]
        )
    target_data = {"exitCode": 0, "topResumedComponents": [TARGET]}
    if scenario == "split-screen":
        target_data = {
            "exitCode": 0,
            "topResumedComponents": [TARGET, SOURCE],
            "splitScreenMarkerCount": 2,
        }
    events.extend(
        [
            wrapper(scenario, cycle, session, "target_launched", target_data),
            wrapper(scenario, cycle, session, "scenario_complete"),
        ]
    )
    return events


def positive_report():
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
            "requestedBlock": 10,
            "targetDetected": 10,
            "backDispatched": 10,
            "leftTarget": 10,
            "returnedSource": 10,
        },
        "blockSessionsComplete": True,
        "safetyViolations": [],
        "timeoutCount": 0,
        "failedEventCount": 0,
        "latencyUpperBoundMs": {"backRequestP95": 180},
    }


def complete_events():
    events = []
    for scenario, count in (("recents", 5), ("split-screen", 5), ("screen-lock", 1)):
        for cycle in range(1, count + 1):
            events.extend(session_events(scenario, cycle))
    return events


def complete_report(events=None):
    return analyse(
        complete_events() if events is None else events,
        positive_report(),
        expected_recents=5,
        expected_split_screen=5,
        expected_screen_lock=1,
    )


class S07DeviceStateReportTest(unittest.TestCase):
    def test_complete_matrix_passes(self):
        report = complete_report()

        self.assertTrue(report["sampleGatePassed"])
        self.assertTrue(report["safetyGatePassed"])
        self.assertEqual("S07_DEVICE_STATE_GATE_PASSED", report["provisionalDecision"])

    def test_back_in_recents_context_is_a_hard_stop(self):
        events = complete_events()
        target = next(
            event
            for event in events
            if event["scenario"] == "recents"
            and event["cycle"] == 2
            and event["kind"] == "companion_event"
        )
        events.append(
            companion("recents", 2, target["sessionId"], "back_requested")
        )

        report = complete_report(events)

        self.assertFalse(report["safetyGatePassed"])
        self.assertEqual("STOP_S07_DEVICE_STATE_PATH", report["provisionalDecision"])

    def test_missing_screen_lock_cycle_is_not_ready(self):
        events = [event for event in complete_events() if event["scenario"] != "screen-lock"]

        report = complete_report(events)

        self.assertFalse(report["sampleGatePassed"])
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_split_screen_without_both_activities_is_a_hard_stop(self):
        events = complete_events()
        target = next(
            event
            for event in events
            if event["scenario"] == "split-screen"
            and event["cycle"] == 1
            and event["kind"] == "target_launched"
        )
        target["data"]["topResumedComponents"] = [TARGET]

        report = complete_report(events)

        self.assertFalse(report["safetyGatePassed"])
        self.assertEqual("STOP_S07_DEVICE_STATE_PATH", report["provisionalDecision"])

    def test_target_launch_without_foreground_observation_is_a_hard_stop(self):
        events = [
            event
            for event in complete_events()
            if not (
                event["scenario"] == "recents"
                and event["cycle"] == 1
                and event["kind"] == "companion_event"
                and TARGET
                in (
                    event["data"]["event"].get("data", {}).get(
                        "resumedComponents", []
                    )
                )
            )
        ]

        report = complete_report(events)

        self.assertFalse(report["safetyGatePassed"])
        self.assertEqual("STOP_S07_DEVICE_STATE_PATH", report["provisionalDecision"])

    def test_evidence_warning_is_a_hard_stop(self):
        report = complete_report()

        apply_warnings(report, ["invalid JSON"])

        self.assertFalse(report["safetyGatePassed"])
        self.assertEqual("STOP_S07_DEVICE_STATE_PATH", report["provisionalDecision"])


if __name__ == "__main__":
    unittest.main()
