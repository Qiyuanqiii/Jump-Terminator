import json
import unittest

from scripts.s08_pip_report import analyse


SOURCE_COMPONENT = "com.jumpterminator.testsource/.SourceActivity"
SOURCE_PACKAGE = "com.jumpterminator.testsource"
TARGET_COMPONENT = "com.jumpterminator.testtarget/.TargetActivity"
TARGET_PACKAGE = "com.jumpterminator.testtarget"


def ready_data(requested_block, lease_deadline):
    return {
        "scenario": "block",
        "mode": "armed",
        "requestedBlock": requested_block,
        "requestedAllowed": 0,
        "sourceComponent": SOURCE_COMPONENT,
        "targetComponent": TARGET_COMPONENT,
        "executor": "shizuku_user_service",
        "authorizationProtocol": "s0.4-1",
        "ownerBound": True,
        "ownerUidSource": "binder",
        "ownerUid": 10418,
        "ownerUserId": 0,
        "ownerPackage": "com.jumpterminator.s02",
        "ownerSigningCertificateSha256": ["a" * 64],
        "oneTimeCapability": True,
        "capabilityFingerprint": "b" * 16,
        "ruleSnapshotSha256": "c" * 64,
        "leaseDurationMs": 140_000,
        "leaseDeadlineElapsedMs": lease_deadline,
        "finalActionSerialization": "authorization_lock",
    }


def wrapper(scenario, cycle, session, kind, data=None, tick=0):
    base = cycle * 10_000
    return {
        "schema": "s0.8-1",
        "scenario": scenario,
        "cycle": cycle,
        "sessionId": session,
        "kind": kind,
        "wallClockMs": 1_700_000_000_000 + base + tick,
        "elapsedRealtimeMs": 100_000 + base + tick,
        "data": data or {},
    }


def embedded(scenario, cycle, session, wrapper_kind, event, tick):
    return wrapper(
        scenario,
        cycle,
        session,
        wrapper_kind,
        {
            "raw": json.dumps(event, separators=(",", ":"), sort_keys=True),
            "event": event,
        },
        tick,
    )


def companion(scenario, cycle, session, kind, data=None, tick=0):
    event = {
        "schema": "s0.2-1",
        "sessionId": session,
        "kind": kind,
        "wallClockMs": 1_700_000_000_000 + cycle * 10_000 + tick,
        "elapsedRealtimeMs": 100_000 + cycle * 10_000 + tick,
        "data": data or {},
    }
    return embedded(scenario, cycle, session, "companion_event", event, tick)


def pip_event(scenario, cycle, session, role, kind, tick, **values):
    event = {
        "schema": "s0.8-pip-1",
        "sessionId": session,
        "role": role,
        "kind": kind,
        "wallClockMs": 1_700_000_000_000 + cycle * 10_000 + tick,
        "elapsedRealtimeMs": 100_000 + cycle * 10_000 + tick,
        **values,
    }
    return embedded(scenario, cycle, session, "pip_event", event, tick)


def task(display_id, task_id, package, component, mode):
    return {
        "displayId": display_id,
        "taskId": task_id,
        "packageName": package,
        "windowingMode": mode,
        "visible": True,
        "activityComponents": [component],
    }


def snapshot(cycle, top_component, pinned_package=None, tick=40):
    top_package = top_component.split("/")[0]
    top_task = task(0, 500 + cycle, top_package, top_component, "fullscreen")
    tasks = [top_task]
    pinned_tasks = []
    if pinned_package:
        pinned_component = (
            SOURCE_COMPONENT if pinned_package == SOURCE_PACKAGE else TARGET_COMPONENT
        )
        pinned = task(0, 800 + cycle, pinned_package, pinned_component, "pinned")
        tasks.append(pinned)
        pinned_tasks.append(pinned)
    return {
        "schema": "s0.8-activity-snapshot-1",
        "capturedWallClockMs": 1_700_000_000_000 + cycle * 10_000 + tick,
        "capturedElapsedRealtimeMs": 100_000 + cycle * 10_000 + tick,
        "rawActivitySha256": "A" * 64,
        "pictureInPictureActive": bool(pinned_tasks),
        "pictureInPictureReportedCount": len(pinned_tasks),
        "displays": [
            {
                "displayId": 0,
                "topResumedComponents": [top_component],
                "tasks": tasks,
            }
        ],
        "topResumed": [{"displayId": 0, "component": top_component}],
        "windowingTasks": tasks,
        "pinnedTasks": pinned_tasks,
    }


def session_events(scenario, cycle):
    prefix = 0xA0 if scenario == "target-preexisting-pip" else 0xB0
    session = f"{prefix + cycle:032x}"
    role = "target" if scenario == "target-preexisting-pip" else "source"
    pinned_package = TARGET_PACKAGE if role == "target" else SOURCE_PACKAGE
    operation = (
        "expand_pinned_target"
        if scenario == "target-preexisting-pip"
        else "source_pip_reveals_target"
    )
    if scenario == "target-preexisting-pip":
        boundary_snapshot = snapshot(cycle, SOURCE_COMPONENT, TARGET_PACKAGE, 45)
        events = [
            wrapper(scenario, cycle, session, "scenario_started", tick=1),
            pip_event(
                scenario, cycle, session, role, "pip_requested", 10, accepted=True
            ),
            pip_event(
                scenario, cycle, session, role, "pip_mode_changed", 20, active=True
            ),
            wrapper(
                scenario,
                cycle,
                session,
                "pip_entered",
                {
                    "expectedPinnedPackage": TARGET_PACKAGE,
                    "snapshot": snapshot(
                        cycle, SOURCE_COMPONENT, TARGET_PACKAGE, 25
                    ),
                },
                tick=26,
            ),
            companion(
                scenario,
                cycle,
                session,
                "ready",
                ready_data(1, 200_000),
                tick=30,
            ),
            companion(
                scenario,
                cycle,
                session,
                "foreground_changed",
                {
                    "state": "picture_in_picture",
                    "component": SOURCE_COMPONENT,
                    "resumedComponents": [SOURCE_COMPONENT],
                    "pinnedPackages": [TARGET_PACKAGE],
                    "pictureInPictureActive": True,
                },
                tick=35,
            ),
            wrapper(
                scenario,
                cycle,
                session,
                "source_presented_with_pip",
                {
                    "snapshot": snapshot(
                        cycle, SOURCE_COMPONENT, TARGET_PACKAGE, 40
                    )
                },
                tick=41,
            ),
        ]
        final_snapshot = snapshot(cycle, TARGET_COMPONENT, None, 55)
    else:
        boundary_snapshot = snapshot(cycle, TARGET_COMPONENT, SOURCE_PACKAGE, 50)
        events = [
            wrapper(scenario, cycle, session, "scenario_started", tick=1),
            companion(
                scenario,
                cycle,
                session,
                "ready",
                ready_data(1, 200_000),
                tick=5,
            ),
            wrapper(
                scenario,
                cycle,
                session,
                "target_underlay_ready",
                {
                    "exitCode": 0,
                    "snapshot": snapshot(cycle, TARGET_COMPONENT, None, 10),
                },
                tick=11,
            ),
            companion(
                scenario,
                cycle,
                session,
                "foreground_changed",
                {
                    "state": "source",
                    "component": SOURCE_COMPONENT,
                    "resumedComponents": [SOURCE_COMPONENT],
                    "pinnedPackages": [],
                    "pictureInPictureActive": False,
                },
                tick=20,
            ),
            wrapper(
                scenario,
                cycle,
                session,
                "source_observed",
                {"snapshot": snapshot(cycle, SOURCE_COMPONENT, None, 25)},
                tick=26,
            ),
            pip_event(
                scenario, cycle, session, role, "pip_requested", 30, accepted=True
            ),
            pip_event(
                scenario, cycle, session, role, "pip_mode_changed", 40, active=True
            ),
            companion(
                scenario,
                cycle,
                session,
                "foreground_changed",
                {
                    "state": "picture_in_picture",
                    "component": TARGET_COMPONENT,
                    "resumedComponents": [TARGET_COMPONENT],
                    "pinnedPackages": [SOURCE_PACKAGE],
                    "pictureInPictureActive": True,
                },
                tick=42,
            ),
            companion(
                scenario,
                cycle,
                session,
                "source_context_invalidated",
                {
                    "reason": "picture_in_picture",
                    "resumedComponents": [TARGET_COMPONENT],
                    "pinnedPackages": [SOURCE_PACKAGE],
                    "pictureInPictureActive": True,
                },
                tick=43,
            ),
        ]
        final_snapshot = snapshot(cycle, TARGET_COMPONENT, SOURCE_PACKAGE, 50)
    events.extend(
        [
            wrapper(
                scenario,
                cycle,
                session,
                "pip_boundary_observed",
                {
                    "operation": operation,
                    "expectedPinnedPackage": pinned_package,
                    "snapshot": boundary_snapshot,
                },
                tick=51,
            ),
            wrapper(
                scenario,
                cycle,
                session,
                "target_presented",
                {"exitCode": 0, "snapshot": final_snapshot},
                tick=56,
            ),
            companion(
                scenario,
                cycle,
                session,
                "foreground_changed",
                {
                    "state": (
                        "target"
                        if scenario == "target-preexisting-pip"
                        else "picture_in_picture"
                    ),
                    "component": TARGET_COMPONENT,
                    "resumedComponents": [TARGET_COMPONENT],
                    "pinnedPackages": (
                        []
                        if scenario == "target-preexisting-pip"
                        else [SOURCE_PACKAGE]
                    ),
                    "pictureInPictureActive": scenario == "source-pip-target",
                },
                tick=60,
            ),
            wrapper(
                scenario,
                cycle,
                session,
                "monitor_stop_requested",
                {"observationSeconds": 3},
                tick=80,
            ),
            companion(
                scenario,
                cycle,
                session,
                "complete",
                {"reason": "stop_requested", "detections": 0, "actions": 0},
                tick=85,
            ),
            wrapper(
                scenario,
                cycle,
                session,
                "scenario_complete",
                {
                    "result": "zero_action_observed",
                    "targetDetections": 0,
                    "backRequests": 0,
                    "monitorCompletionObserved": True,
                },
                tick=90,
            ),
        ]
    )
    return events


def positive_timeline():
    session = "c" * 32
    events = [
        {
            "schema": "s0.2-1",
            "sessionId": session,
            "kind": "ready",
            "wallClockMs": 1_700_100_000_001,
            "elapsedRealtimeMs": 200_001,
            "data": ready_data(10, 300_000),
        }
    ]
    for sequence in range(1, 11):
        for offset, kind, data in (
            (1, "target_detected", {"sequence": sequence}),
            (2, "back_requested", {"sequence": sequence, "dispatched": True}),
            (
                3,
                "left_target",
                {
                    "sequence": sequence,
                    "leftTarget": True,
                    "returnedSource": True,
                },
            ),
        ):
            tick = sequence * 10 + offset
            events.append(
                {
                    "schema": "s0.2-1",
                    "sessionId": session,
                    "kind": kind,
                    "wallClockMs": 1_700_100_000_000 + tick,
                    "elapsedRealtimeMs": 200_000 + tick,
                    "data": data,
                }
            )
    events.append(
        {
            "schema": "s0.2-1",
            "sessionId": session,
            "kind": "complete",
            "wallClockMs": 1_700_100_000_200,
            "elapsedRealtimeMs": 200_200,
            "data": {"reason": "count_reached", "detections": 10, "actions": 10},
        }
    )
    return events


def positive_report(count=10):
    events = positive_timeline()
    session = events[0]["sessionId"]
    return {
        "schema": "s0.2-report-1",
        "eventCount": len(events),
        "executors": ["shizuku_user_service"],
        "sessions": {session: {"scenario": "block"}},
        "warnings": [],
        "authorization": {
            "allSessionsBinderDerived": True,
            "allSessionsSigningIdentityResolved": True,
            "allSessionsOneTimeCapability": True,
            "allSessionsRuleSnapshotBound": True,
        },
        "sampleCounts": {
            "requestedBlock": 10,
            "targetDetected": count,
            "backDispatched": count,
            "leftTarget": count,
            "returnedSource": count,
        },
        "blockSessionsComplete": count == 10,
        "safetyViolations": [],
        "timeoutCount": 0,
        "failedEventCount": 0,
        "latencyUpperBoundMs": {"backRequestP95": 180},
    }


def complete_events():
    events = []
    for scenario in ("target-preexisting-pip", "source-pip-target"):
        for cycle in range(1, 6):
            events.extend(session_events(scenario, cycle))
    return events


def complete_report(events=None, positive=None, positive_events=None):
    return analyse(
        complete_events() if events is None else events,
        positive_report() if positive is None else positive,
        positive_timeline() if positive_events is None else positive_events,
        expected_target_preexisting_pip=5,
        expected_source_pip_target=5,
    )


class S08PipReportTest(unittest.TestCase):
    def test_complete_matrix_passes(self):
        report = complete_report()

        self.assertTrue(report["sampleGatePassed"])
        self.assertTrue(report["safetyGatePassed"])
        self.assertEqual("S08_PIP_CONTEXT_GATE_PASSED", report["provisionalDecision"])

    def test_back_in_pip_context_is_an_immediate_hard_stop(self):
        events = complete_events()
        session = next(
            event["sessionId"]
            for event in events
            if event["scenario"] == "target-preexisting-pip" and event["cycle"] == 2
        )
        events.append(
            companion(
                "target-preexisting-pip",
                2,
                session,
                "back_requested",
                {"dispatched": True},
                tick=58,
            )
        )

        report = complete_report(events)

        self.assertTrue(report["hardStopObserved"])
        self.assertFalse(report["safetyGatePassed"])
        self.assertEqual("STOP_S08_PIP_CONTEXT_PATH", report["provisionalDecision"])

    def test_missing_system_pinned_confirmation_is_not_ready(self):
        events = complete_events()
        boundary = next(
            event
            for event in events
            if event["scenario"] == "source-pip-target"
            and event["cycle"] == 3
            and event["kind"] == "pip_boundary_observed"
        )
        boundary["data"]["snapshot"]["pinnedTasks"] = []

        report = complete_report(events)

        self.assertFalse(report["hardStopObserved"])
        self.assertFalse(report["sampleGatePassed"])
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_incomplete_fullscreen_positive_regression_is_not_ready(self):
        report = complete_report(positive=positive_report(9))

        self.assertFalse(report["hardStopObserved"])
        self.assertFalse(report["fullscreenPositiveControl"]["gatePassed"])
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_boundary_requires_structured_display_windowing_top_and_pinned_data(self):
        events = complete_events()
        boundary = next(
            event
            for event in events
            if event["scenario"] == "target-preexisting-pip"
            and event["cycle"] == 1
            and event["kind"] == "pip_boundary_observed"
        )
        boundary["data"]["snapshot"]["displays"] = []

        report = complete_report(events)
        session = report["pipNegativeStress"]["target-preexisting-pip"]["sessions"][0]

        self.assertFalse(session["readinessChecks"]["boundary.structuredDisplays"])
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_cross_session_embedded_event_is_not_ready_even_when_raw_matches(self):
        events = complete_events()
        embedded_event = next(
            event
            for event in events
            if event["scenario"] == "target-preexisting-pip"
            and event["cycle"] == 1
            and event["kind"] == "companion_event"
        )
        embedded_event["data"]["event"]["sessionId"] = "d" * 32
        embedded_event["data"]["raw"] = json.dumps(
            embedded_event["data"]["event"], separators=(",", ":"), sort_keys=True
        )

        report = complete_report(events)

        session = report["pipNegativeStress"]["target-preexisting-pip"]["sessions"][0]
        self.assertFalse(
            session["readinessChecks"]["embeddedCompanionIdentityAndRawValid"]
        )
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_source_presentation_must_really_be_top_while_target_is_pinned(self):
        events = complete_events()
        source_presented = next(
            event
            for event in events
            if event["scenario"] == "target-preexisting-pip"
            and event["cycle"] == 2
            and event["kind"] == "source_presented_with_pip"
        )
        snapshot_value = source_presented["data"]["snapshot"]
        snapshot_value["topResumed"] = [
            {"displayId": 0, "component": TARGET_COMPONENT}
        ]
        snapshot_value["displays"][0]["topResumedComponents"] = [TARGET_COMPONENT]

        report = complete_report(events)

        session = report["pipNegativeStress"]["target-preexisting-pip"]["sessions"][1]
        self.assertFalse(
            session["readinessChecks"]["sourcePresented.expectedTopResumed"]
        )
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_source_context_must_precede_pip_active_boundary(self):
        events = complete_events()
        source_wrapper = next(
            event
            for event in events
            if event["scenario"] == "source-pip-target"
            and event["cycle"] == 1
            and event["kind"] == "companion_event"
            and event["data"]["event"].get("kind") == "foreground_changed"
            and event["data"]["event"].get("data", {}).get("state") == "source"
        )
        source_wrapper["data"]["event"]["elapsedRealtimeMs"] += 100
        source_wrapper["data"]["raw"] = json.dumps(
            source_wrapper["data"]["event"], separators=(",", ":"), sort_keys=True
        )

        report = complete_report(events)

        session = report["pipNegativeStress"]["source-pip-target"]["sessions"][0]
        self.assertFalse(session["readinessChecks"]["sourcePipCausalOrder"])
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_scenario_summary_must_match_embedded_action_counts(self):
        events = complete_events()
        summary = next(
            event
            for event in events
            if event["scenario"] == "source-pip-target"
            and event["cycle"] == 4
            and event["kind"] == "scenario_complete"
        )
        summary["data"]["backRequests"] = 1

        report = complete_report(events)

        session = report["pipNegativeStress"]["source-pip-target"]["sessions"][3]
        self.assertFalse(
            session["readinessChecks"]["scenarioSummaryMatchesEmbeddedEvents"]
        )
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_monitor_completion_is_required_before_session_summary(self):
        events = complete_events()
        events = [
            event
            for event in events
            if not (
                event["scenario"] == "target-preexisting-pip"
                and event["cycle"] == 3
                and event["kind"] == "companion_event"
                and event["data"]["event"].get("kind") == "complete"
            )
        ]

        report = complete_report(events)

        session = report["pipNegativeStress"]["target-preexisting-pip"]["sessions"][2]
        self.assertFalse(session["readinessChecks"]["monitorCompletedExactlyOnce"])
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_preexisting_pip_must_never_establish_source_context(self):
        events = complete_events()
        session_id = next(
            event["sessionId"]
            for event in events
            if event["scenario"] == "target-preexisting-pip"
            and event["cycle"] == 4
        )
        events.append(
            companion(
                "target-preexisting-pip",
                4,
                session_id,
                "foreground_changed",
                {
                    "state": "source",
                    "component": SOURCE_COMPONENT,
                    "resumedComponents": [SOURCE_COMPONENT],
                    "pinnedPackages": [TARGET_PACKAGE],
                    "pictureInPictureActive": True,
                },
                tick=37,
            )
        )

        report = complete_report(events)

        session = report["pipNegativeStress"]["target-preexisting-pip"]["sessions"][3]
        self.assertFalse(
            session["readinessChecks"]["sourceContextNeverEstablishedWhilePip"]
        )
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_pip_state_and_invalidation_must_carry_matching_topology(self):
        events = complete_events()
        for item in events:
            if (
                item["scenario"] == "source-pip-target"
                and item["cycle"] == 2
                and item["kind"] == "companion_event"
            ):
                embedded_event = item["data"]["event"]
                data = embedded_event.get("data", {})
                if (
                    embedded_event.get("kind") == "foreground_changed"
                    and data.get("state") == "picture_in_picture"
                ):
                    data["component"] = SOURCE_COMPONENT
                    data["resumedComponents"] = [SOURCE_COMPONENT]
                if embedded_event.get("kind") == "source_context_invalidated":
                    data["pictureInPictureActive"] = False
                    data["pinnedPackages"] = []
                item["data"]["raw"] = json.dumps(
                    embedded_event, separators=(",", ":"), sort_keys=True
                )

        report = complete_report(events)

        session = report["pipNegativeStress"]["source-pip-target"]["sessions"][1]
        self.assertFalse(session["readinessChecks"]["pipForegroundStateObserved"])
        self.assertFalse(
            session["readinessChecks"]["sourceInvalidationCarriesPipTopology"]
        )
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_negative_ready_must_bind_armed_shizuku_owner_authorization(self):
        events = complete_events()
        ready_wrapper = next(
            event
            for event in events
            if event["scenario"] == "target-preexisting-pip"
            and event["cycle"] == 1
            and event["kind"] == "companion_event"
            and event["data"]["event"].get("kind") == "ready"
        )
        ready = ready_wrapper["data"]["event"]
        ready["data"].update(
            {
                "mode": "observe",
                "requestedBlock": 0,
                "executor": "none",
                "ownerBound": False,
                "oneTimeCapability": False,
            }
        )
        ready_wrapper["data"]["raw"] = json.dumps(
            ready, separators=(",", ":"), sort_keys=True
        )

        report = complete_report(events)

        session = report["pipNegativeStress"]["target-preexisting-pip"]["sessions"][0]
        self.assertFalse(session["readinessChecks"]["ready.armedBlockConfiguration"])
        self.assertFalse(session["readinessChecks"]["ready.shizukuExecutor"])
        self.assertFalse(session["readinessChecks"]["ready.ownerIdentityBound"])
        self.assertFalse(
            session["readinessChecks"]["ready.capabilityRuleAndLeaseBound"]
        )
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_negative_lease_must_cover_pip_boundary_and_observation(self):
        expired_during_observation = complete_events()
        ready_wrapper = next(
            event
            for event in expired_during_observation
            if event["scenario"] == "source-pip-target"
            and event["cycle"] == 1
            and event["kind"] == "companion_event"
            and event["data"]["event"].get("kind") == "ready"
        )
        ready = ready_wrapper["data"]["event"]
        ready["data"]["leaseDeadlineElapsedMs"] = ready["elapsedRealtimeMs"] + 1
        ready_wrapper["data"]["raw"] = json.dumps(
            ready, separators=(",", ":"), sort_keys=True
        )

        expired_report = complete_report(expired_during_observation)

        session = expired_report["pipNegativeStress"]["source-pip-target"][
            "sessions"
        ][0]
        self.assertTrue(
            session["readinessChecks"]["ready.capabilityRuleAndLeaseBound"]
        )
        self.assertFalse(
            session["readinessChecks"]["authorizationLeaseCoversPipObservation"]
        )
        self.assertEqual("NOT_READY", expired_report["provisionalDecision"])

        duration_mismatch = complete_events()
        ready_wrapper = next(
            event
            for event in duration_mismatch
            if event["scenario"] == "target-preexisting-pip"
            and event["cycle"] == 2
            and event["kind"] == "companion_event"
            and event["data"]["event"].get("kind") == "ready"
        )
        ready = ready_wrapper["data"]["event"]
        ready["data"]["leaseDurationMs"] = 1
        ready_wrapper["data"]["raw"] = json.dumps(
            ready, separators=(",", ":"), sort_keys=True
        )

        duration_report = complete_report(duration_mismatch)

        session = duration_report["pipNegativeStress"]["target-preexisting-pip"][
            "sessions"
        ][1]
        self.assertFalse(
            session["readinessChecks"]["ready.capabilityRuleAndLeaseBound"]
        )
        self.assertEqual("NOT_READY", duration_report["provisionalDecision"])

    def test_monitor_completion_action_counts_cannot_hide_missing_events(self):
        events = complete_events()
        complete_wrapper = next(
            event
            for event in events
            if event["scenario"] == "source-pip-target"
            and event["cycle"] == 3
            and event["kind"] == "companion_event"
            and event["data"]["event"].get("kind") == "complete"
        )
        complete = complete_wrapper["data"]["event"]
        complete["data"]["detections"] = 1
        complete["data"]["actions"] = 1
        complete_wrapper["data"]["raw"] = json.dumps(
            complete, separators=(",", ":"), sort_keys=True
        )

        report = complete_report(events)

        session = report["pipNegativeStress"]["source-pip-target"]["sessions"][2]
        self.assertFalse(
            session["readinessChecks"]["monitorCompletionCountsMatchEmbeddedEvents"]
        )
        self.assertFalse(
            session["readinessChecks"]["monitorCompletedWithZeroActionCounts"]
        )
        self.assertFalse(
            session["safetyChecks"]["monitorCompletionReportsNoPipActions"]
        )
        self.assertTrue(report["hardStopObserved"])
        self.assertEqual("STOP_S08_PIP_CONTEXT_PATH", report["provisionalDecision"])

    def test_fullscreen_sequences_must_be_unique_and_causally_paired(self):
        duplicate_sequences = positive_timeline()
        for event in duplicate_sequences:
            if event["kind"] in {"target_detected", "back_requested", "left_target"}:
                event["data"]["sequence"] = 1

        duplicate_report = complete_report(positive_events=duplicate_sequences)

        self.assertFalse(
            duplicate_report["fullscreenPositiveControl"]["checks"]
            ["timelineSequencesExactlyOneToTen"]
        )
        self.assertEqual("NOT_READY", duplicate_report["provisionalDecision"])

        reversed_pair = positive_timeline()
        detected = next(
            event
            for event in reversed_pair
            if event["kind"] == "target_detected" and event["data"]["sequence"] == 5
        )
        back = next(
            event
            for event in reversed_pair
            if event["kind"] == "back_requested" and event["data"]["sequence"] == 5
        )
        back["elapsedRealtimeMs"] = detected["elapsedRealtimeMs"] - 1
        back["wallClockMs"] = detected["wallClockMs"] - 1

        reversed_report = complete_report(positive_events=reversed_pair)

        self.assertTrue(
            reversed_report["fullscreenPositiveControl"]["checks"]
            ["timelineSequencesExactlyOneToTen"]
        )
        self.assertFalse(
            reversed_report["fullscreenPositiveControl"]["checks"]
            ["timelineSequencesCausallyPaired"]
        )
        self.assertEqual("NOT_READY", reversed_report["provisionalDecision"])

    def test_fullscreen_ready_actions_complete_chain_and_lease_are_required(self):
        late_ready = positive_timeline()
        ready = next(event for event in late_ready if event["kind"] == "ready")
        last_left = next(
            event
            for event in late_ready
            if event["kind"] == "left_target" and event["data"]["sequence"] == 10
        )
        ready["elapsedRealtimeMs"] = last_left["elapsedRealtimeMs"] + 1
        ready["wallClockMs"] = last_left["wallClockMs"] + 1

        late_ready_report = complete_report(positive_events=late_ready)

        self.assertFalse(
            late_ready_report["fullscreenPositiveControl"]["checks"]
            ["timelineReadyActionsCompleteCausalChain"]
        )
        self.assertEqual("NOT_READY", late_ready_report["provisionalDecision"])

        early_complete = positive_timeline()
        ready = next(event for event in early_complete if event["kind"] == "ready")
        complete = next(
            event for event in early_complete if event["kind"] == "complete"
        )
        complete["elapsedRealtimeMs"] = ready["elapsedRealtimeMs"] - 1
        complete["wallClockMs"] = ready["wallClockMs"] - 1

        early_complete_report = complete_report(positive_events=early_complete)

        self.assertFalse(
            early_complete_report["fullscreenPositiveControl"]["checks"]
            ["timelineReadyActionsCompleteCausalChain"]
        )
        self.assertEqual("NOT_READY", early_complete_report["provisionalDecision"])

        expired_lease = positive_timeline()
        ready = next(event for event in expired_lease if event["kind"] == "ready")
        first_detection = next(
            event
            for event in expired_lease
            if event["kind"] == "target_detected" and event["data"]["sequence"] == 1
        )
        ready["data"]["leaseDeadlineElapsedMs"] = (
            first_detection["elapsedRealtimeMs"] - 1
        )

        expired_lease_report = complete_report(positive_events=expired_lease)

        self.assertFalse(
            expired_lease_report["fullscreenPositiveControl"]["checks"]
            ["timelineActionsWithinReadyLease"]
        )
        self.assertEqual("NOT_READY", expired_lease_report["provisionalDecision"])

    def test_expected_cycle_counts_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "greater than or equal to 1"):
            analyse(
                complete_events(),
                positive_report(),
                positive_timeline(),
                expected_target_preexisting_pip=0,
                expected_source_pip_target=5,
            )

    def test_positive_report_cannot_pass_without_matching_timeline(self):
        report = complete_report(positive_events=[])

        self.assertFalse(report["fullscreenPositiveControl"]["gatePassed"])
        self.assertFalse(report["sampleGatePassed"])
        self.assertEqual("NOT_READY", report["provisionalDecision"])


if __name__ == "__main__":
    unittest.main()
